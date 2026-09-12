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
/short TICKER  (or /long TICKER) → refresh the data template outside the
bot and upload it as dennis_data.xlsx → run the pre-filled master prompt in
Claude/GPT → paste the output back → validation + cost report → tweak in
chat if needed → Approve ✅ → /render TICKER → shareable link
```

(The upload is the only data route. The bot runs on Linux and does not drive
Excel; the refresh happens on the operator's own machine.)

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
| A `/proof` **cannot** spend — it raises at the boundary rather than reaching ElevenLabs, so $0 survives a mistyped command | `TTSEngine.guard_free_only` (`free_only=True`), asserted again immediately before the paid branch |
| Draft audio can never become a final render (its word timings are interpolated) | `render_long` / `render_short` refuse `tts.draft` |
| Mock and draft audio is never loudness-normalised (normalising a placeholder tone is what made a render come out silent) | `CompositeSpec.normalise_audio`; the limiter stays on either way |
| A plate name that resolves to nothing fails the build rather than drawing an empty area | `Registry.require`; `compose.build_layers` raises `TemplateError` |
| A value with no slot, a row whose length disagrees with its header, or a plate a chapter TYPE may not use is rejected before a frame is drawn | `pipeline/plate_tags.py` `check_bound`, `Registry.plates_for_chapter` |
| A room plate that declares neither a host anchor nor `hostAnchor: false` fails `Registry.verify` | `pipeline/plates.py`; a refusal is data, an omission is a bug |
| A PNG on disk the registry does not name, or a frame it names and cannot find, fails the ingest | `scripts/ingest_kit.py --check`, `Registry.verify`, `/kit doctor` |
| Every plate is reachable by a template, a chapter type or the renderer — artwork with no route to the screen is reported | `pipeline/gates.py` `reachable_plates`, `/kit doctor` |
| Visuals: owned library → cache → fetch → filler; a missing item **never** aborts a render | `pipeline/broll.py` content engine, `pipeline/memes.py` |
| The data vendor is never named on screen — scripts are hard-rejected if they try | parsers' vendor block; filing overlays carry a generic "FROM THE 10-K" chip |
| `[SCREENGRAB]` tags **block** the render until the operator's capture exists | `validate_long_script` + `assets/custom/` |
| Every figure that reaches the SCREEN is re-read against the data, not just the spoken ones | `pipeline/gates.py` `onscreen_fact_check` |
| A price chart drawn from the synthetic floor rather than the live feed **blocks** a final render | `pipeline/gates.py` `check_prices`; `PriceSeries.degraded` survives the cache and rides on the manifest |
| 1–2 memes max per LONG (information-first) | `validate_long_script` meme cap |
| Audio timestamps are the master clock (`ffprobe` + ElevenLabs alignment) | `pipeline/timeline.py` (pure, exhaustively tested) |
| Screener is data-only, never spends, degrades gracefully | `pipeline/screener.py` |
| Uploads are private or scheduled — never public from a machine | `pipeline/youtube.py` `build_body` |
| Every free source degrades to "unavailable"; none can fail a run | `pipeline/sources.py` |
| The status page binds loopback only (no auth, shows internals) | `pipeline/status_page.py` `serve` |

---

## What the bot checks before you approve

Six gates run unprompted between the script landing and any spend, **on
both lanes**. Silence means proceed; every finding carries a line
reference. They are notes and blocks, never rewrites — the writer decides.

A SHORT used to run none of them — only the cost report and the audio
check — on the higher-volume format, so an invented figure, a named data
vendor or stale data went straight to the Approve button.

| Gate | What it reads | Blocks? |
|---|---|---|
| **fact-check** | every number the narration says out loud, spelled-out numerals included, re-read against the loaded `CompanyData`. No magnitude floor (the unit scale is derived from the series, and spoken shorthand is followed by powers of a thousand); percentages checked against the rate series or the growth it implies; a claim that names a period is checked against THAT column; period-over-period changes count as claims. A number attached to its own subject by a preposition is not read as a claim about a metric named elsewhere | **blocks** |
| **on-screen fact-check** | every figure in a `[PLATE]`'s cells, against the same export, with the plate's own `unit=` applied — the numbers a viewer can pause on | warns |
| **voice linter** | what `assets/voice_bible.md` forbids: hype adjectives, exclamation marks, anything that reads as a call, a construction used twice in one script, and ~20 seconds of explanation with no turn in it. A data vendor named on screen is the one **block** — it would be spoken and captioned | mostly warns |
| **direction linter** | the delivery vocabulary and its ceilings, read off `pipeline/direction.py`: one direction a sentence, never two adjacent, per-script caps on the tags that stop working when repeated, and no shouted word. A tag the bible refuses is named as refused, and the **block** is the lowercase spelling the ElevenLabs docs use — `[laughs]` is not a tag to the bracket grammar at all, so it would be read out and captioned | mostly warns |
| **confession ledger** | whether a confession repeats one already used, read off the ledger `standing.py` keeps. Nothing here asks for one — roughly one video in three earns it | warns |
| **data freshness** | the workbook's own as-of date, not its mtime. A date it cannot READ blocks too — an unreadable date is not evidence of freshness. Reads ISO, US and day-first slashes, `3-Sep-2026`, `Sep 3, 2026` and a raw Excel serial | blocks when stale or unreadable (`DATA_STALE_BLOCKS=false` to make it advisory) |
| **audio** | placeholder oscillators reaching a FINAL render outside `MOCK_MODE` | blocks |
| **type budgets** | every figure and line a `[PLATE]` writes, against the `maxChars` the kit derived for THAT box — the role's narrowest box is the floor behind it. Checked here because it is a property of the script: the same failure at render time costs a forty-minute build to learn a label is six characters too long | blocks |
| **valuation moves** | whether the valuation chapter goes from forward multiples straight to the reverse DCF without ever placing the subject against its peer set — move 3 of four, and the one it has always skipped | blocks |
| **kit doctor** | unresolved plate names, slots a script left unfilled, and which plates no template, chapter type or renderer can reach | blocks on unresolved |
| **skeptic** | an LLM read of the finished script as a hostile investor. Notes only, never offline | never |

---

## Repository map

Every path below is checked by `tests/test_docs.py`. A map that names a file
which is not there sends a reader hunting for a module that was deleted a
fortnight ago, which is exactly what this one did.

```
config.py                typed settings (pydantic-settings) — every cap/knob,
                         voice placeholder + audition shortlist
main.py                  bot entrypoint
pipeline/
  models.py              data contracts: ShortScript (strict JSON), LongScript
                         + the Dennis tag grammar, CompanyData (six periods),
                         CostReport, JobRecord, Candidate
  parser_short.py        tolerant JSON extraction + the SHORT's inline tags
  parser_long.py         offset-aware tag tokenizer + the chapter trailer
  tagging.py             the shared tag tokenizer, for both formats

  plates.py              THE PLATE REGISTRY — the read side of the design kit.
                         143 plates keyed family/name, each with its canvas,
                         exportScale, frames, playback, slot geometry and type
                         roles; the palette's eight colour roles; the host and
                         room ROLES; the sixteen chapter types and what each
                         may use. `require()` raises rather than degrading
  plate_tags.py          `[PLATE: …]` — the director names the plate and writes
                         what goes on it. Rejects an unknown plate, an
                         undeclared slot, a row whose length disagrees with its
                         header, and a plate the chapter type may not use
  plate_frames.py        playing plates and filling their slots: type is set in
                         the face, size, weight and colour role the KIT
                         declares, and `maxChars` is a hard limit — read off
                         the BOX the copy lands in, with the role's narrowest
                         box as the fallback floor
  shots.py               shot templates — a FORMAT is an ordered list of SHOTS
                         and it is data. Spans, anchors, `max_hold_s` ceilings
  compose.py             the template and the script, turned into an ordered
                         list of layers; the two-shot split, the room-angle
                         rotation, the invariants and the kit's own budgets
  host.py                Dennis on screen — a cut-out solved onto a room's
                         host-anchor, or a FRAMING (close-up, medium) placed on
                         its eye line; the glance, the wardrobe, the flap
  marks.py               hand-drawn line primitives and type fitting
  media_frames.py        foreign media gets a frame (`frames/` family)
  chart.py               the data path for a declared chart region, and the
                         range marks on a multiples strip — nothing else; the
                         plate draws the furniture
  rasters.py             what the kit does not draw: captions, alpha clips,
                         figure animation, and solving a mark onto its target

  tts.py                 ElevenLabs with-timestamps client + cache + budgets
  direction.py           THE DELIVERY VOCABULARY: one table of what each tag
                         becomes per model tier, the ceilings, and the tags the
                         bible refuses by name. The prompts are generated from
                         it and the linter reads it
  local_tts.py           the free draft voice (Piper) + sentence-anchored timings
  timeline.py            THE MASTER CLOCK: beats/anchors -> cue times
  segments.py            per-segment encoding: content-hash cache, parallel,
                         resumable
  render_common.py       ffmpeg wrappers, encode profiles, compositing engine
  render_short.py        the vertical formats, from a shot template and the
                         audio clock — SHORT, EARNINGS, MACRO
  render_long_shots.py   the LONG from chapter templates, through that same
                         engine — a resolver and an entry point, no compositor
  render_long.py         the tag-driven LONG: fast-cut concat engine, the
                         two-shot, the scribble solver (rewritten in Stage 3)
  storyboard.py          storyboard contact sheet — see the cut before paying
  reach.py               how much of the plate library a script actually reaches

  gates.py               the automated gates: fact-check (spoken AND on-screen
                         figures, re-read against the export), the voice linter,
                         the confession ledger, data freshness, placeholder
                         audio, and `/kit doctor` — including which plates no
                         template, chapter type or renderer can reach
  form.py                what the writer is asked for, DERIVED from the shot
                         templates and the kit's own character budgets
  llm.py                 LLM routing — local first, hosted as the fallback

  prices.py              Yahoo price history behind an interface (cached)
  company_data.py        two-sheet Excel export reader + filing screenshots
  filings.py             10-K auto-screenshot pipeline
  article_lookup.py      the real article behind a headline the script wrote
  broll.py               the content engine: [CLIP], [IMG]/[PRODUCT], [MEME],
                         [SCREENGRAB] — cached, attributed
  memes.py               owned meme library (meme_index.json) + providers
  sources.py             free feeds: 8-K + EX-99.1, Form 4, 13F, FRED, IR RSS
  audio_assets.py        where the sound came from, and whether it is real
  screener.py            Yahoo + StockTwits lanes + digest + move context
  alerts.py              intraday watch: moves, volume, earnings, filings
  standing.py            thesis book, confession ledger, ranked idea queue

  jobs.py                persisted async job queue (one render at a time)
  cost.py                spend ledger, gates, report builders
  workspace.py           per-ticker/date dirs, approvals, chat context
  script_edit.py         in-chat revision: line/range edits, find-replace, undo
  publish.py             subtitles and the upload metadata package
  youtube.py             upload (private/scheduled, never public) + retention
  delivery.py            gdrive (default) / s3 / telegram / local
  repurpose.py           best ~58s of a LONG -> 9:16 SHORT (free)
  thumbnail.py           the cover — a frame from the video
  byproducts.py          golden-frame regression + thumbnails and end screens
  status_page.py         read-only localhost view (loopback, no auth)
  cleanup.py             RETENTION_DAYS disk hygiene (keeps caches)
bot/
  handlers.py            BotCore (all logic, Telegram-free) + PTB glue
  prompts.py             master-prompt filling + the plate catalogue, generated
                         from the registry (never a hand-kept list)
  keyboards.py           Approve / Swap clip / Cancel, candidate buttons
kit/                     THE DESIGN DELIVERY, as shipped: engine/ (the
                         generator), per-family manifest.json, roles.json,
                         fonts/, INGEST.md. The PNGs under assets/plates/ are
                         built from this and are not edited by hand
assets/
  plates/                the materialised kit: 143 plates in fourteen families
                         plus plates-registry.json, written by the ingest
  voice_bible.md         the voice, and what the linter checks against
  fonts, brand, channel, backgrounds, overlays, sfx, broll_library,
  meme_library, custom/ ([SCREENGRAB] drops), hook_bank.json
templates/
  shots/                 one file per FORMAT: short, earnings, macro, long
  chapters/              one file per chapter TYPE — all sixteen
  master_prompt_*.md     the writing prompts
  dennis_data_template.xlsx
fixtures/                mock scripts / Pexels / Wikimedia / TTS / prices /
                         screener JSON / company data
samples/                 sample MP4s + their manifests, rendered from fixtures
deploy/                  systemd units + cleanup timer + bootstrap.sh
scripts/
  ingest_kit.py          run the kit's own engine, reconcile what it emits
                         against the signed-off manifests, install the PNGs and
                         write plates-registry.json. `--check` verifies an
                         installed kit without rebuilding it
  kit_engine.js          the node entry point the ingest drives
  render_samples.py      render the committed samples from fixtures
  gen_assets.py          procedural placeholders for everything not drawn
  gen_fixtures.py, fetch_sfx.py, contact_sheet.py, audit_placement.py
workspace|cache|state/   runtime (gitignored)
```

---

## Setup

### Local (development)

**Install `git-lfs` before you clone.** `samples/*.mp4` are Git LFS objects.
A clone made without it silently gets 132-byte pointer files instead of video,
and the fifteen sample measurements in `tests/test_short_holds.py` then fail on
`moov atom not found` and `could not convert string to float: ''` — which read
like a broken FFmpeg and are nothing of the sort.

```bash
sudo apt install git-lfs && git lfs install
git clone <your-repo-url> dennis && cd dennis
# already cloned without it? `git lfs pull` fetches the media in place.
```

Then:

```bash
sudo apt install ffmpeg nodejs npm fonts-dejavu-core  # FFmpeg 6+, Node 18+
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci                                      # the kit's rasteriser (build-time only)
.venv/bin/python scripts/gen_assets.py      # placeholder sfx + room tone
.venv/bin/python scripts/ingest_kit.py kit  # the 143 drawn plates -> assets/plates
.venv/bin/python -m pytest tests/           # offline, zero network calls
.venv/bin/python scripts/render_samples.py  # sample MP4s from fixtures
```

**`ingest_kit.py` is not optional.** `gen_assets.py` draws placeholders for
everything the kit does *not* draw; the plates themselves come from the kit's
own JS engine and are a build product, not a commit. Skip the ingest and
`load_plates()` raises `PlateError: no plates-registry.json in …`, which fails
about 180 tests and every render. Node is build-time only — nothing under
`pipeline/` shells out to it, so no published video depends on it — but it is
needed here and by `tests/test_budgets.py`, which drives the engine directly.

### Windows (the render box) — see the full runbook below

**The target platform is Linux, and on Windows that means WSL2.**
`deploy/bootstrap.sh` is the installer for both WSL2 and a bare VPS — it is
the same install, and the differences are detected rather than configured.
The step-by-step sequence from a clean machine is
[Running it on Windows](#running-it-on-windows--the-full-sequence) below; the
short version is:

```bash
# inside WSL (Ubuntu), from a clone on the LINUX filesystem
sudo bash deploy/bootstrap.sh /opt/dennis
sudo nano /opt/dennis/.env                  # token + operator chat id
sudo systemctl enable --now dennis
```

**GPU.** NVENC is detected with a real smoke encode, not by asking ffmpeg
what it supports — `h264_nvenc` is listed on machines with no NVIDIA driver
at all and fails at `Cannot load libcuda.so.1` the moment a render starts,
which is the normal case under WSL2 without the GPU passed through. Every
failure, including a wedged driver that never returns, falls back to libx264
silently. If the GPU runs out of encode sessions partway through a parallel
render, the remaining segments finish on the CPU rather than losing the job.

The probe encodes a **640×360** frame, and the size is load-bearing. It used
to probe 128×128, which NVENC refuses outright — `InitializeEncoder failed:
invalid param (8): Frame Dimension less than the minimum supported value` —
so a working RTX 3060 was reported as having no usable encoder and every
render on it went to libx264. When the probe does fail, the encoder's own
reason is logged at `info`, not `debug`: "listed but a smoke encode failed"
on its own reads as "no GPU" and ends the investigation.

### VPS (production)

Identical:

```bash
sudo bash deploy/bootstrap.sh /opt/dennis
sudo nano /opt/dennis/.env
sudo systemctl enable --now dennis
```

The bootstrap checks everything up front — root, apt, a Python ≥ 3.11 the
service user can execute, FFmpeg 6+, Node 18+, the destination filesystem —
and aborts with one readable message naming the fix rather than
half-installing. Then: apt deps, any missing Git LFS media, the venv from the
**pinned** `pyproject.toml`, headless Chromium *and its system libraries*,
generated assets, **the design kit** (`npm ci` + `scripts/ingest_kit.py`), the
free local voice, the offline suite, and the service + daily cleanup timer. It
is idempotent — safe to re-run after a pull.

**The kit is built before the suite is run, and that ordering is the point.**
`assets/plates/` is a build product, not a commit, and the suite checks it —
so an installer that ran the tests without building it reported ~180 failures
on every clean install and told the operator they were real.

**What it will and will not stop for.** A step aborts the run only if the bot
cannot work without it. Headless Chromium and the local Piper voice are
optional: each warns, names its retry, and the install carries on to the test
suite and the systemd units, because a box that cannot install a *free draft
voice* still deserves a working bot. The last line of the run says whether the
voice is present, so a degraded install never looks like a clean one. Skip the
voice outright with `--skip-piper`, with `sudo SKIP_PIPER=1 bash …` (on sudo's
own command line — `SKIP_PIPER=1 sudo …` loses it to `env_reset`), or with
`LOCAL_TTS_ENABLED=false` in an existing `.env`. All three are read; a skipped
run leaves the `LOCAL_TTS_*` settings from an earlier install alone.

No display server, no
ImageMagick.

Note it does not pin `python3.11` by name: Ubuntu 24.04, which is what WSL
installs by default, ships 3.12 and has no `python3.11` package at all.

**Encode politeness.** The render box is somebody's daily-driver desktop and
renders are unattended, so FFmpeg is capped to about half the cores and its
processes run at `nice 10` — slower, but the machine stays usable. The cap is
an **aggregate**: the parallel segment encoder divides it among its workers
(`workers × threads ≤ budget`) rather than each worker taking the whole
thing. Tune with `RENDER_THREAD_FRACTION`, `RENDER_THREADS` (0 = derive) and
`RENDER_BELOW_NORMAL_PRIORITY` in `.env`.

**These stay on when NVENC does.** The cap covers `-filter_threads` and
`-filter_complex_threads`, not just the encode, and the filtergraph is the
bottleneck in this pipeline — moving the encode to the GPU leaves the CPU work
that the cap exists to bound, and makes it a larger share of what is left.
Raising the fraction on a GPU box is a measurement, not a consequence of
having one.

### Running it on Windows — the full sequence

**You run it inside WSL2, not natively.** That is not a workaround: the render
path is FFmpeg filtergraphs, headless Chromium and a systemd service, and all
three are first-class on Linux and awkward-to-broken on native Windows. The one
feature that ever needed native Windows — Excel COM automation — has been
deleted outright in favour of the external refresh plus upload, so there is
nothing left on that side of the line.

From a clean Windows 11 machine, in order:

**1. Install WSL2 and Ubuntu.** In PowerShell *as Administrator*:

```powershell
wsl --install -d Ubuntu
```

Reboot when it asks. Open **Ubuntu** from the Start menu and set your Linux
username and password. Everything from here is typed in that Ubuntu window,
not in PowerShell.

**2. Turn systemd on, and give the VM swap.** Two files, one restart.

*Systemd* — WSL ships with it off, and without it the bot cannot run as a
service that survives a reboot. Inside Ubuntu:

```bash
sudo nano /etc/wsl.conf
```

```ini
[boot]
systemd=true
```

*Memory and swap* — this one is not optional on a render box, and its failure
mode gives you nothing to read. WSL2 defaults to half the host's RAM **and no
swap at all**, so a render-heavy test run does not fail: the kernel kills the
VM, and your Ubuntu window closes with no message, no traceback and no exit
code. With swap configured the same run gets slow instead of fatal. In
**PowerShell**, create `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=24GB
swap=24GB
processors=4
```

Scale `memory` to the machine (roughly half the host's RAM) and keep `swap` at
least equal to it. Then, still in **PowerShell**:

```powershell
wsl --shutdown
```

Reopen Ubuntu. `ps -p 1 -o comm=` should now print `systemd`, and
`free -h` should show a non-zero Swap row.

**3. Clone onto the Linux filesystem.** Under your Linux home — `~/` — and
**never** under `/mnt/c`. See the warning below; this is the single most
expensive mistake available here.

```bash
sudo apt update && sudo apt install -y git git-lfs
git lfs install
git clone <your-repo-url> ~/dennis
```

`git-lfs` goes in **before** the clone: `samples/*.mp4` are LFS objects, and a
clone made without it gets 132-byte pointer files that fail fifteen tests with
errors pointing at FFmpeg rather than at the download. If you have already
cloned without it, `cd ~/dennis && git lfs pull` fixes it in place.

**4. Run the bootstrap.** It is the same installer as the VPS, and the
differences are detected rather than configured.

```bash
sudo bash ~/dennis/deploy/bootstrap.sh /opt/dennis
```

It checks root, apt, Python ≥ 3.11, FFmpeg 6+, Node 18+, that the `dennis`
service user can actually execute the interpreter it picked, and the
destination filesystem — up front, and aborts with one readable message naming
the fix rather than half-installing. It installs to `/opt/dennis` and runs the
bot as a dedicated `dennis` service user, which is why the commands below are
`sudo -u dennis`. Then: apt dependencies, any missing LFS media, the venv from
the pinned `pyproject.toml`, headless Chromium and its system libraries,
generated assets, **the design kit built from its own engine**, the offline
test suite, and the service plus the daily cleanup timer. It is idempotent —
safe to re-run after every `git pull`.

**5. Configure.**

```bash
sudo nano /opt/dennis/.env
```

At minimum `TELEGRAM_BOT_TOKEN` (from @BotFather) and `OPERATOR_CHAT_IDS`.
Leave `MOCK_MODE=true` for now. Every key is listed in the configuration
reference below, and `.env.example` documents each one in place.

If you do not know your chat id: start the bot, message it, and it will reply
with the id to add.

**6. Start it.**

```bash
sudo systemctl enable --now dennis
systemctl status dennis
journalctl -u dennis -f          # live logs; Ctrl-C to stop watching
```

Message the bot `/help` in Telegram. If it answers, you are running.

**7. Prove it end to end before spending anything.** With `MOCK_MODE=true`,
run one whole video — `/short EXMPL`, upload `dennis_data.xlsx`, run the
prompt, paste the script back, `Approve ✅`, `/render EXMPL`. It costs
nothing and exercises every seam. Only then follow *Going live* above.

**Day-to-day**

| task | command (inside Ubuntu) |
|---|---|
| update to the latest code | `cd ~/dennis && git pull && sudo bash deploy/bootstrap.sh /opt/dennis` |
| restart after an `.env` change | `sudo systemctl restart dennis` |
| watch the logs | `journalctl -u dennis -f` |
| stop it | `sudo systemctl stop dennis` |
| run in the foreground instead (no systemd) | `cd /opt/dennis && sudo -u dennis .venv/bin/python main.py` |
| run the tests | `cd /opt/dennis && sudo -u dennis .venv/bin/python -m pytest -q` |

**The machine sleeps, and that is fine.** This is somebody's desktop, not a
server. Nothing in the bot assumes it is awake: `/batch` queues renders for
the overnight window and simply finds the work still there next time the
window opens, and the daily cleanup timer catches up when it misses a run.
Closing the Ubuntu window does not stop the service, but shutting Windows
down does — WSL stops with it, and both resume when you next open Ubuntu.

**Never delete `cache/tts`.** It is the only directory in this repo whose
contents cost money. TTS is cached on a content hash of the script text and
the delivery directives in it, globally and forever — which is what makes
re-rendering the same approved script to fix visual placement free: kit
changes, plate manifests, `CHAPTER_CUE_SFX` and `hold=` values are all
outside the cache key, so the second render of a script is $0 and reuses the
same voice. Clear it and every one of those scripts re-bills in full at the
per-1k-character rate on its next render. `RETENTION_DAYS` never touches it,
and neither should anybody clearing space: prune `cache/segments` (encoded
video, regenerates for free) and old workspaces instead.

**Keep everything off `/mnt/c`.** `workspace/`, `cache/` and `state/` must
live on the Linux filesystem. `cache/segments` is thousands of small clips
that get stat'd on every render to decide what to reuse, and every one of
those crosses the 9p/drvfs translation layer — the cost lands precisely on
the operation that is supposed to make a re-render cheap. The bootstrap
refuses a destination under `/mnt`, warns if the checkout itself is there,
and the bot warns at startup if `WORKSPACE_DIR`, `CACHE_DIR` or `STATE_DIR`
resolve there (symlinks included).

**Getting files in and out.** Windows can reach the Linux side at
`\\wsl$\Ubuntu\home\<you>\` in Explorer, and Ubuntu can reach Windows at
`/mnt/c/Users/<you>/`. Copying a finished MP4 out that way is fine — it is a
one-off read. Working *from* there is what is slow.

**Native Windows.** Not supported. `deploy/bootstrap.ps1` and
`deploy/install-task.ps1` are kept so a future native deployment has a
starting point, but they are **unmaintained** and nothing tests them.

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
   prompt automatically, from a live quote rather than yesterday's close.
2. The numbers arrive by upload, which is the only data route: the bot sends
   `templates/dennis_data_template.xlsx`, you refresh it outside the bot and
   upload the result as `dennis_data.xlsx`. A successful upload **withdraws
   any approval** on that workspace — the approval pins the script's hash,
   which does not change when the data underneath it does, so new numbers
   have to be re-read and re-approved. Optionally upload raw screenshot PNGs for
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
   spend). It also states how much of the kit this script reaches —
   `Kit: 7 of 442 assets · 4 families · 7 beat-library scenes` — which is the
   number that says whether the video will look like the last one. A script
   under the floor gets a warning naming the beats that carry a figure and
   have no drawing to put it in; it is a judgement call, never a blocker. If the LONG used `[ASSET: slug]` tags, the bot attaches each
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
6. `/render TICKER` (SHORT) or `/render_long TICKER`. Before spending, there
   are two free passes — see the tier table below. `/proof TICKER` is the one
   that answers "what will this look like?"; `/draft TICKER` (LONG) answers
   "does the timing work?". Both use the local neural voice (Piper) when the
   box has one and the mock hum otherwise, never ElevenLabs. Draft audio is
   listenable, but its word timings are exact per sentence and interpolated
   within one, so judge pacing and composition, not lip-sync — and the
   renderers refuse to build a final from it. Progress and failures arrive as
   messages.

   **The four tiers, once:**

   | mode | visuals | voice | resolution | cost |
   |---|---|---|---|---|
   | `MOCK_MODE=true` | fake (prices, imagery, memes, filings, delivery) | mock hum | full | $0 |
   | `/proof TICKER [short\|long]` | **live** — prices, Pexels, Wikimedia, memes, SEC, charts | free local (Piper) | **full** | $0 |
   | `/draft TICKER` (LONG only) | live | free local (Piper) | half | $0 |
   | `/render` / `/render_long` | live | **paid** ElevenLabs, one generation | full | ~one generation |

   `MOCK_MODE` proves the pipeline runs and tells you nothing about what
   ships, because it fakes everything a viewer would see. `/proof` is the
   inverse: everything real except the one thing that costs money. It renders
   at full resolution on purpose — whether type is legible at phone size is a
   resolution question, so the cheaper passes cannot answer it — and buys its
   speed from the encoder instead (`veryfast`, crf 26). It cannot reach the
   paid voice: `TTSEngine` raises `PaidVoiceForbidden` rather than spend, so
   the guarantee survives a mistyped command. Its output is named
   `*_proof.mp4`, marked `draft_audio` in the manifest, and never delivered.
7. Delivery: Google Drive link (default) posted in chat with attribution
   (Pexels + Wikimedia credits written beside the file);
   `/repurpose TICKER` afterwards cuts the best two or three ~58s windows
   of the LONG into free vertical SHORTs (non-overlapping, best first).
8. `/status`, `/cancel TICKER`, `/cost` any time. `/ideas` is the ranked
   backlog (fed by every screen and by any thesis that moves), `/thesis
   TICKER` re-checks what you said against today's numbers, and `/batch`
   queues renders to run unattended overnight.
9. **When a thesis moves, `/update TICKER`.** Shipping a video pins what it
   claimed — the hook, the conclusion verbatim, the two or three things it
   asserted — and `/thesis` re-reads the numbers behind it. When they have
   moved materially the bot says so and names the command. `/update` is its
   own prompt with its own spine (what I said → what happened → was I right →
   what now), carrying the previous video's own words, so the writer grades a
   real claim instead of inventing one. It is explicit on purpose: whether a
   covered name is an update or a fresh take is an editorial call and stays
   yours. The screener's 30-day cooldown does not apply — being recently
   covered is the precondition for an update, not a reason to skip it.

## Command reference

Every command the bot registers, in the order you meet them. `TICKER` is
always the symbol (`EXMPL`); anything in `[brackets]` is optional. Commands
that touch a workspace use the **active** one when you omit the ticker — the
last `/short`, `/long` or `/update` you ran in that chat.

`tests/test_docs.py` checks this table against the handlers the bot actually
registers, in both directions, so a command cannot be added or renamed without
this section failing.

### Starting a video

| command | what it does |
|---|---|
| `/short TICKER` | Opens a SHORT (9:16, 60–75s), pulls a live quote for the move context, and asks for the refreshed workbook. `prompt_short.md` follows the upload. |
| `/long TICKER` | Opens a LONG (16:9 deep dive). Two steps: Step 1 returns ranked angles, you reply with a number, Step 2 is the writing prompt. |
| `/update TICKER` | Revisits a name already covered — what I said, what happened, was I right, what now. One step, no angle to pick. Refuses (and points at `/long`) when no thesis is on file. |
| `/headline TICKER <text or URL>` | A SHORT about one specific headline. `/headline macro <text>` for an index/macro take. Mode is detected (company / earnings / macro) and can be forced with a leading `a:`, `b:` or `c:`. |
| `/prompts` | Re-sends the active workspace's pre-filled prompt. |

### Reviewing and editing the script

| command | what it does |
|---|---|
| `/script` | The stored script, numbered, so `/edit N` and it agree. |
| `/edit N <text>` | Replaces line N. `N-M` for a range; no text deletes the line. |
| `/replace old => new` | Fixes a figure or a phrase by its own words. `all:` prefix replaces every occurrence. |
| `/undo` | Steps back one revision. |

An edit that does not parse never lands. Every edit that does re-runs the
gates, re-prices, and drops the approval — nothing renders from a version
nobody read.

### Rendering

| command | what it does |
|---|---|
| `/render TICKER` | Renders the approved script for that ticker's lane. |
| `/render_long TICKER` | Forces the LONG, for a ticker that has both. |
| `/render_short TICKER` | Forces the SHORT, for a ticker that has both. |
| `/proof TICKER [short\|long]` | Full-resolution look test: live visuals, free local voice, `$0`. The pass that answers "what will this look like?". Writes `short_proof.mp4` / `long_proof.mp4` — never over a paid final. |
| `/draft TICKER` | LONG only, half resolution, free voice. Answers "does the timing work?". |
| `/repurpose TICKER` | Cuts the best two or three ~58s windows of a finished LONG into free vertical SHORTs. |
| `/status` | The job queue, with the by-product links the delivery produced — thumbnail, `.srt`, upload package, credits. Jobs left QUEUED by a restart are picked back up rather than blocking their ticker. |
| `/cancel TICKER` | Cancels queued and running jobs plus any pending approval. |

**Every render writes to a temp file and `os.replace`s into position**, after
its length has been checked, so a failed re-render cannot destroy the good
final that was already there. **Segment boundaries are quantised to whole
frames at plan time** with the remainder carried forward, so the picture no
longer creeps ahead of the voice across a long cut.

**The lane decides the format, and it is declared rather than inferred.**
`/short` or `/long` sets it once; `current_format()` returns it. It used to be
read off which script files existed, with LONG winning unconditionally, so one
stray paste made `/render`, `/proof`, `/script`, `/edit`, `/undo`, `/upload`
and `/batch` all target the wrong script for the rest of the day. A script file
that disagrees with the lane is reported, not followed.

**A pasted script routes by the lane too**, never by whether it starts with a
brace. A paste that looks cut off — a JSON body that never closes, or a message
sitting exactly on Telegram's 4,096-character split point — is refused with
"send it as a .txt file" rather than saved as half a script, and the master
prompts now ask the model to hand the script back as a downloadable `.txt` with
only the human-facing summary in the chat body.

### Publishing

| command | what it does |
|---|---|
| `/upload TICKER [short\|long\|clip] [YYYY-MM-DD HH:MM]` | YouTube upload — private, or scheduled at that time. Never public. A format reaches either lane, or a repurposed clip. A bare date means `PUBLISH_HOUR` in `PUBLISH_TIMEZONE`, and a naive time is read in that zone rather than UTC. The thumbnail and the `.srt` go up with the video; a dropped upload resumes rather than starting a second one. |
| `/scheduled` | What is queued to publish, and when. |
| `/retention [TICKER]` | Per-chapter drop-off. No ticker aggregates the evidence across everything published. |

### Finding the next one

| command | what it does |
|---|---|
| `/screen [trending\|value\|all]` | Ranked candidates. Trending → SHORT, value → LONG, plus the update lane (covered names whose thesis has moved). |
| `/ideas` | The ranked backlog, fed by every screen and by any thesis that moves. |
| `/idea TICKER <why>` | Adds one by hand. |
| `/unidea TICKER` | Drops one. |
| `/thesis [TICKER]` | What we said about a name, re-checked against today's numbers. No ticker lists every thesis on file with its status. |
| `/watch [TICKER \| drop TICKER]` | Intraday watch. Published names join automatically. |
| `/earnings TICKER YYYY-MM-DD [bmo\|amc]` | Records a print date so the bot flags it both sides. |

### Housekeeping

| command | what it does |
|---|---|
| `/batch [TICKER [fmt] \| run \| clear]` | Queues renders to run unattended overnight. Harmless when the machine is off — nothing expires. |
| `/cost` | Month-to-date spend against the cap. |
| `/kit doctor` | Unresolved tag keys, artwork nothing has ever used, PNGs with no registry entry. The gap list is the input to the next batch of art. |
| `/help`, `/start` | The command list, in chat. |

### Things that are not commands

- **Paste a script** (message or `.txt`) into the chat and it is taken as the
  script for the active workspace — short or long is detected, not declared.
- **Reply with a number** while a LONG is awaiting an angle and it is read as
  your angle pick, not as a script.
- **Upload `dennis_data.xlsx`** any time to override the numbers.
- **Upload a PNG** to satisfy a `[SHOW FILING:]` or `[ASSET:]` tag.
- **The buttons**: `Approve ✅` arms a render, `Swap clip 🔄` rotates a
  `[CLIP]` pick, `Cancel ✖️` withdraws a pending approval.

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

#### Getting the numbers in (the primary route)

The bot runs on Linux, so it does not drive Excel. The refresh happens
**outside** the bot — on the Windows side, by hand or by an external
workflow — and the result is pasted into a clean workbook as **values**
and dropped into the chat as `dennis_data.xlsx`.

Values-only is the expected shape, and it is the shape the reader is built
for: it opens with `data_only=True`, so it reads saved values and never
formula text. Add-in formulas do not travel — they only resolve on a machine
with the add-in signed in — so a workbook that still contains them arrives
looking empty.

The upload is validated **before** it replaces anything. A rejected upload
never overwrites the workbook already in the workspace, and each failure is
named in terms of what to go and fix:

| What is wrong | What you get told |
|---|---|
| No `Snapshot` sheet | which sheets *are* there, and to re-export |
| Formulas, no saved values | how many, and to Paste Special ▸ Values |
| Every field blank | that it was probably saved before the add-in settled |
| `#CIQINACTIVE` / `Not Signed In` / `#NAME?` in a **required** field | the field, the marker in the cell, and to sign the terminal in — **refused** |
| the same in an optional field | a warning; treated as missing |
| A different company's workbook | both tickers, and the command to open a workspace for the other one — **refused** |
| Older than `DATA_MAX_AGE_DAYS` | its age and its as-of date — **refused** by default (`DATA_STALE_BLOCKS=false` makes it a warning) |

An unresolved marker is **not** the same as an empty cell, and conflating
them is how a video ends up titled `#CIQINACTIVE`: a text field accepts the
marker, so the required-field check passes and it reaches the screen. Every
such marker now coerces to missing. Plain `#N/A` is deliberately *not* on
that list — on a values-only export it is the ordinary way a mnemonic says
"no figure for this company", and treating it as a failure would reject
perfectly good workbooks for thinly-covered small-caps.

**Freshness comes from the workbook's own as-of date.** That is the only
thing that knows when the numbers were actually pulled, and it is the date
the operator can see in the file they exported. Not the file's mtime —
re-saving or copying a workbook resets that without changing a single
number, which is exactly the case the gate exists to catch.

---

## Configuration reference (env / .env)

| Var | Default | Meaning |
|---|---|---|
| `MOCK_MODE` | `true` | master switch: mock all paid APIs + local delivery |
| `MOCK_TTS` / `MOCK_PRICES` / `MOCK_SCREENER` | unset | per-subsystem overrides; unset follows `MOCK_MODE`. Whatever is on is named at startup, in `/status`, in the digest and on the approval report — a fixture ticker and a real one used to look identical |
| `TELEGRAM_BOT_TOKEN` | — | from @BotFather (free; required even in mock) |
| `OPERATOR_CHAT_IDS` | — | allow-list; empty denies all. `["123456789"]`, `123456789` and `123,456` all parse |
| `BRAND_HANDLE` | `@dennisreads` | signed on the SHORT's closing card |
| `SHORT_OPEN_STYLE` | `bug` | where the signature card goes in a SHORT: `bug` (a corner mark, so the video opens cold on the hook), `tail` (no open at all — `e_close` still runs), `full` (the original full-frame bumper). Tunable against retention data rather than by editing code |
| `SHORT_OPEN_BUG_S` | 1.6 | how long the corner bug holds |
| `CHAPTER_CUE_SFX` | `keyboard_clack` | the sound a LONG's chapter opener fires, 0.15s ahead of the picture so it announces the opener rather than reacting to it. A key from the sfx taxonomy; blank turns the cue off. It is a signpost, not atmosphere — `keyboard_clack` reads as one because it is diegetic (he is typing the chapter title), where a `ding` reads as a notification. `paper_rustle` and `ding` are the alternatives worth auditioning; the choice can only be made by listening, which is why it is a setting |
| `ELEVEN_VOICE_ID_SHORT/LONG` | — | **placeholder** — the Dennis voice is a one-line change (shortlist in `config.py`) |
| `SHORT_MAX_CHARS` / `LONG_MAX_CHARS` | 800 / 22000 | TTS budgets, rejected pre-spend |
| `USD_PER_1K_CHARS` | unset | **override only.** Unset means the selected model's list price (`config.ELEVEN_USD_PER_1K_CHARS`): turbo/flash and v3-conversational $0.05, v3 and multilingual_v2 $0.10. Lookup is **exact** and a model the table does not know **raises** rather than defaulting — a guessed rate is how a spend cap comes to meter at the wrong speed. Set this when a price moves or a model is newer than the table. Not a display figure: `SpendLedger` meters `MONTHLY_SPEND_CAP` with it |
| `MONTHLY_SPEND_CAP` | 50.0 | hard code-level gate |
| `ELEVEN_MODEL_ID` | unset | the ElevenLabs model, by name. `eleven_turbo_v2_5` (default), `eleven_multilingual_v2`, `eleven_v3`. **v3 is the only model that performs delivery** — eight of the ten direction tags do something only there — and it is twice turbo's price; the tags are what that buys. `eleven_v3_conversational` is a *different*, cheaper model for the Agents Platform, not a v3 variant. See *Delivery direction* below |
| `ELEVEN_USE_PREMIUM` | false | **deprecated** — picks between turbo and multilingual_v2, and only when `ELEVEN_MODEL_ID` is unset. Prefer naming the model |
| `GIPHY_API_KEY` / `TENOR_API_KEY` | — | optional [MEME] fallbacks (library first) |
| `DELIVERY_BACKEND` | gdrive | gdrive · s3 · telegram · local |
| `GDRIVE_CREDENTIALS` / `GDRIVE_ROOT_FOLDER_ID` | — | Drive delivery |
| `LOCAL_TTS_ENABLED` / `LOCAL_TTS_MODEL` | true / — | free draft voice (Piper .onnx); drafts fall back to mock, never to paid |
| `RETENTION_DAYS` | 14 | cleanup horizon (caches never pruned). **`cache/tts` holds audio that was paid for and must never be deleted** — see *Never delete `cache/tts`* below |
| `SCREEN_TOP_N` / `COOLDOWN_DAYS` | 8 / 30 | screener caps |
| `SCREEN_DIGEST_CRON` | `30 7 * * 1-5` | digest, `SCREEN_TIMEZONE` (ET) |
| `ALERTS_ENABLED` / `ALERT_POLL_MINUTES` | true / 15 | intraday watch on covered names |
| `ALERT_MOVE_PCT` / `ALERT_COOLDOWN_MINUTES` | 6.0 / 180 | when it speaks, and how rarely it repeats |
| `FRED_API_KEY` | — | free macro series for `/headline macro`; absent = unavailable |
| `WHISPER_ENABLED` | false | optional webcast transcription; never blocks |
| `YOUTUBE_ENABLED` / `YOUTUBE_CREDENTIALS` | false / — | upload as private or scheduled; never public |
| `BYPRODUCTS_ENABLED` | true | thumbnails, social cards, end screens per render |
| `STATUS_PAGE_ENABLED` / `STATUS_PAGE_PORT` | false / 8787 | read-only localhost view |
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
  the feed dies) — never a TradingView screenshot. The floor is a plain
  seeded walk with no invented spike on the final bar, it is flagged
  `degraded` all the way through the cache and onto the render manifest,
  and it **blocks** a final render outside `MOCK_MODE`: a fabricated chart
  on a channel whose premise is real numbers is not a warning-level event. Two styles: the clean
  branded card and a crude hand-drawn "marker" napkin chart on black;
  a SHORT picks via `chart_style`, a LONG via `[CHART: metric style=marker]`.
- **The director names the plate.** `[PLATE: numbers-sheet-4r-16x9 | unit=$M
  | head=FY21,…,LTM | label-1=Revenue | row-1=400,452,471,491,496,496 |
  band=3]` — the tag carries its own content and the renderer only places it.
  Rejected rather than shipped wrong: an unknown plate, an undeclared slot, a
  row whose length disagrees with its header, a plate the chapter's TYPE is
  not allowed to use, and a plate in the wrong aspect. The compact forms
  expand against the slots the plate declares, so an expansion cannot invent
  one.
- **The type budget belongs to the box, not the role.** `slots[name].maxChars`
  is derived from that box's width and the face it is set in;
  `typeRoles[role].maxChars` is the FLOOR — the narrowest slot on the plate
  that sets the role — and stands in where a slot declares none. One number per
  role cannot be right twice: `structure/flow-16x9` sets `caption` in a
  1620-unit strip and again in four 104-unit arrow labels, which hold 103
  characters and 6.
- **Not every slot value is a string.** `tables/multiples-strip`'s `marker-N`
  is a REGION, and it takes a pair of numbers — `marker-3 = t:0.82,
  median:0.41` — where `t` is the subject's position between the peer low and
  the peer high and `median` is the peer set's, on the same scale. Both come
  off `Peers!I`/`Peers!J`, which are a VALUE axis and not the rank in column
  D. A string bound to a region and a pair bound to a text slot are both
  refused; `t` outside 0–1 is a real reading (the subject is off the peer
  range) and passes through unclamped — the renderer puts the dot on the end
  tick and draws a chevron past it.
- **Chapters are a type plus a title.** Sixteen fixed generic types
  (`cold-open`, `the-numbers`, `moat`, `filing-walk`, `short-interest`, … )
  gate the plate library; the title is free text and the only thing that
  reaches the screen. A type may appear twice under different titles, and
  there is no ordinal anywhere — which is what stopped a chapter being moved,
  repeated or cut without redrawing it.
- **Hand-drawn overlay language**: `[SCRIBBLE: style -> target]` draws a mark
  on a figure or a phrase already on screen. The styles ARE the ten drawings
  in the kit's `annotations/` family — `scrawl-oval-wide`,
  `scrawl-oval-tight`, `underline-swipe`, `underline-tight`, `strike-out`,
  `box-scrawl`, `bracket-rows`, `arrow-elbow`, `caret-note`, `tick-marks` —
  mapped in `rasters.SCRIBBLE_MARKS`, listed in every writing prompt off the
  registry on disk, and drawn from the real artwork with a procedural stroke
  as the fallback. A mark is solved onto the TYPE rather than onto the slot
  rectangle, and the VARIANT is chosen by how wide that target turns out to
  be: a wide oval around a four-character cell is a hairline, so the tight one
  is drawn instead. Both formats parse it, and it composites as the top layer.
- **Screen-grab backbone**: `[SCREENGRAB: slug]` composites an operator-
  supplied capture (a broker app, a portfolio P&L, a Google search) —
  image or short screen-record dropped into `assets/custom/`, pad-fit
  (never cover-cropped). It blocks the render until the file exists; the bot
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
- **`[MEME]` is still, `[CLIP]` moves.** A meme is normalised to a frozen PNG
  because the freeze is the joke's timing. A clip is illustration — the visual
  that proves the claim — so an animated source resolved through the clip path
  normalises to a short looping mp4 and plays inside a frames/ plate exactly as
  footage does. Its chain is owned library → cache → Pexels → Giphy → Tenor →
  filler: Pexels is a STOCK library and will never have a specific film or
  sports moment, which used to mean `[CLIP: lebron three pointer]` silently drew
  a blank card. A clip that still lands on filler is a warning on the approval
  report, not just a log line. `[MEME]` keeps `MEME_MAX_PER_LONG` — a joke is
  rationed — and `[CLIP]` stays uncapped, because illustration is information.
- **The writer times the hold.** `[CLIP: lebron three pointer | hold=2.5]` and
  `[MEME: bagholder | hold=2.0]` — seconds on screen, clamped to 0.8–5.0 with a
  warning outside it, because `hold=30` is a slipped decimal point rather than
  an instruction. The bare forms are unchanged and take the format's default.
- **Delivery direction is declared, never inferred.** The writer places
  `[BEAT]`, `[CURIOUS]`, `[SIGH]` and the rest inline; nothing downstream reads
  a sentence and decides it wants one. `pipeline/direction.py` is the single
  table — what each tag becomes on `eleven_v3`, what it falls back to on an
  older model, the ceiling on each, and the ones refused by name — and the
  writing prompts are **generated** from it, so the list a writer is handed is
  the list the pipeline performs. ElevenLabs' "Enhance" pass is deliberately
  not wired in: it puts a model in charge of the register, which is the thing
  the bible, this linter and the fact-check gate exist to keep it out of.
- **Only the paid tier is handed direction.** Which model is configured and
  which voice is about to speak are different questions. Piper honours neither
  audio tags nor SSML — it reads both aloud — so the free draft voice gets the
  clean script, and the direction stays in the cache key so a draft with a
  `[SIGH]` is still a different generation from one without.
- **Mock TTS** synthesizes a low hum at a deterministic words-per-second
  rate (2.7 SHORT / 2.3 LONG) with linear word timestamps, so mock
  renders have realistic pacing and the full timeline logic is exercised.
- **The kit is built by its own engine, at ingest.** `kit/` is the delivery:
  a node generator, a signed-off `manifest.json` per family, and
  `roles.json`. `scripts/ingest_kit.py` runs the engine, reconciles what it
  emits against those manifests, refuses the install if the two disagree, and
  writes `assets/plates/` plus `plates-registry.json`. Nothing under
  `assets/plates/` is edited by hand and no PNG is committed from anywhere
  else. Everything the kit does NOT draw — sfx, b-roll, memes — is
  still procedurally placeheld by `scripts/gen_assets.py` and meant to be
  replaced.
- **Placeholder AUDIO cannot be published.** Every wav in `assets/sfx` is an
  ffmpeg oscillator until `scripts/fetch_sfx.py` replaces it — that script
  pulls licence-clean effects for all 14 cue keys plus the room bed,
  normalises each to one peak, and records source/licence/author per file in
  `assets/sfx/SOURCES.json`. A file with no provenance entry counts as
  generated. Both renderers log a one-line `PLACEHOLDER AUDIO` banner, and
  the same list is a **gate** (`pipeline.gates.check_audio`): a blocking
  finding in the validation report the operator approves from whenever a
  FINAL render outside `MOCK_MODE` would play one, a warning in `MOCK_MODE`
  and on drafts — which is what the offline suite runs on. A banner is
  discipline; the block is the guarantee.
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
.venv/bin/python -m pytest tests/    # ~1050 tests, fully offline
```

**The suite needs the kit built and the LFS media fetched.** Both are the
Setup section above: without `assets/plates/` about 180 tests fail on
`PlateError`, and without the real `samples/*.mp4` fifteen more fail on
`moov atom not found`. Neither is a broken checkout — they are build steps that
have not been run. Node is needed too: `tests/test_budgets.py` drives
`scripts/kit_engine.js` directly to prove the loader rejects an engine file
nothing accounts for.

A conftest guard fails any test that opens a non-localhost socket. The
renderer smoke tests produce real MP4s (reduced resolution) from mock
audio and then assert the cue times that reached the actual FFmpeg
filtergraph match the timeline — the "no hardcoded timings" invariant is
executable. Dedicated tests pin the deletion of the verdict system and
the desk scene, the vendor-name block, the meme cap, and the `[SCREENGRAB]`
blocking loop. `tests/test_docs.py` pins this README against the code: the
command reference in both directions, and every path in the repository map.

Sample artifacts (committed): `samples/sample_short_EXMPL.mp4`
(9:16 "Noise or signal?") and `samples/sample_long_EXMPL.mp4` (16:9
deep-dive), both rendered from `fixtures/` with `MOCK_MODE=true` and zero
network calls:

```bash
.venv/bin/python scripts/render_samples.py all
```

## Troubleshooting

- **`PlateError: no plates-registry.json in …/assets/plates`, and ~180 tests
  fail** — the design kit was never built. `assets/plates/` is a build product
  (`.gitignore`d, ~850MB of PNGs) and comes from the kit's own engine:
  `npm ci && .venv/bin/python scripts/ingest_kit.py kit`. `scripts/gen_assets.py`
  does *not* produce it — it draws placeholders for the things the kit does not
  draw. `deploy/bootstrap.sh` does this for you, before the test suite.
- **`kit_engine: @resvg/resvg-js is not installed`** — `npm ci`. It is a
  build-time dependency of the ingest only; nothing in the render path uses
  Node.
- **`node is not on PATH`** — `apt install nodejs npm`, Node 18+. Ubuntu 22.04
  still ships Node 12 in its own repository; take a current release from
  NodeSource if the version check refuses.
- **15 failures in `test_short_holds.py` (`moov atom not found`,
  `could not convert string to float: ''`)** — `samples/*.mp4` are Git LFS
  pointer files, not video. `apt install git-lfs && git lfs install &&
  git lfs pull`. This is a missing prerequisite, not a broken FFmpeg.
- **`sudo: '.venv/bin/python': command not found`, for a file that is plainly
  there** — the `dennis` service user cannot traverse to the interpreter the
  venv points at. Usual cause: a uv-installed Python under a home directory
  created mode 750. `chmod o+x ~` and `chmod -R o+rX ~/.local/share/uv`, or
  install an interpreter system-wide. The same cause shows up separately as
  `cannot execute '…/.venv/bin/piper': Permission denied`; the bootstrap now
  checks for it in preflight.
- **The bootstrap says "No usable Python found" right after `uv python
  install`** — `sudo` resets `PATH` to `secure_path`, which does not include
  `~/.local/bin`. Link the interpreter somewhere `secure_path` covers:
  `sudo ln -sf "$(uv python find 3.13)" /usr/local/bin/python3.13`.
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
- **`/update TICKER` says "No thesis on file"** — nothing was recorded from a
  previous video for that name, so there is no claim to grade. `/long TICKER`
  for a first-time take; the thesis is pinned when that one ships.

### Windows / WSL2 specifically

- **`sudo systemctl enable --now dennis` fails with "System has not been
  booted with systemd"** — systemd is off. Put `[boot]\nsystemd=true` in
  `/etc/wsl.conf`, run `wsl --shutdown` from PowerShell, reopen Ubuntu, and
  re-run the bootstrap so the unit files enable. Until then run it in the
  foreground: `cd /opt/dennis && .venv/bin/python main.py`.
- **The bootstrap refuses the destination** — it is under `/mnt`. Install to
  the Linux filesystem (`/opt/dennis`), not to a Windows drive.
- **Renders are inexplicably slow, and the second render of the same video is
  no faster** — the checkout or the cache is on `/mnt/c`. Every segment-reuse
  check crosses the 9p translation layer, which is exactly the operation that
  is supposed to make a re-render cheap. Move `WORKSPACE_DIR`, `CACHE_DIR` and
  `STATE_DIR` onto the Linux side; the bot warns about this at startup.
- **The Ubuntu window vanishes mid-render, with no error** — the VM ran out of
  memory and was killed. WSL2 defaults to half the host's RAM and **no swap**,
  so there is nothing to page into and nothing to print. Set `memory` and
  `swap` in `%UserProfile%\.wslconfig` (step 2 above) and `wsl --shutdown`;
  the same run then gets slow rather than fatal.
- **`Cannot load libcuda.so.1` in the logs** — the GPU is not passed through
  to WSL. Nothing to fix: the encoder falls back to libx264 and the render
  finishes.
- **The GPU is definitely there, `nvidia-smi` works, and renders still use
  libx264** — check the log line after "listed but a smoke encode failed": the
  encoder's own reason is printed at `info`. `Frame Dimension less than the
  minimum supported value` means the probe frame was too small, which is a bug
  in this repo rather than in your driver — the probe is 640×360 and anything
  smaller can be refused outright.
- **The bot stops answering overnight** — Windows slept or shut down, which
  takes WSL with it. Expected. Reopen Ubuntu and the service comes back;
  anything queued with `/batch` is still queued.
