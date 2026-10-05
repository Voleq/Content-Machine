# Review findings — bugs and possible improvements

Review of the whole project thread as it stands on `main` at `e2326a6`
(2026-10-04, "cover type that does not read gets a soft shade"). **Nothing
here has been fixed** — this is a log to work from.

**How it was checked.** I read the bot (`main.py`, `bot/`), the job queue,
workspace and approval state, the money path (`cost.py`, `tts.py`, `llm.py`),
delivery and YouTube, the shared ffmpeg layer, the segment cache, and the
newest work (3D Dennis, covers, the short push-in, the rebuild-41 wiring). I
sampled the rest. I also ran `ruff` and the full test suite (results at the
end), plus small reproductions where a claim could be checked cheaply.

**Confidence labels.**

- **verified**: reproduced, or the code path is unambiguous.
- **likely**: the reading is clear, but I didn't run it end to end.
- **possible**: depends on external behaviour (an API, a driver) that I
  couldn't confirm here.

Severities: **High** means what ships, or what costs money, is not what the
operator approved or was told. **Medium** means a feature silently doesn't
work, or works wrongly in a common case. **Low** covers edge cases and
hygiene.

---

## Top of the list

| # | Sev | Where | One line |
|---|-----|-------|----------|
| H1 | High | `pipeline/render_long.py:2237`, `:2339` | Clip swaps change the approval report but the final render ignores them |
| H2 | High | `main.py:128` / `bot/handlers.py:1924` | File pushes never report failure, so the Telegram backend says "(sent in chat)" when nothing arrived |
| H3 | High | `pipeline/filings.py:841` | A failed 10-K screenshot shifts every later screenshot onto the wrong quote |
| H4 | High | `pipeline/gates.py:1776` + `bot/handlers.py:1257` | Macro `/headline` shorts can never be approved with default settings |
| H5 | High | `pipeline/cost.py:80` | A corrupt `spend.json` resets month-to-date spend to $0, so the cap fails **open** |
| H6 | High | `pipeline/llm.py:198` | Hosted LLM spend (OpenAI fallback) is never metered or capped |
| M1 | Med | `pipeline/render_common.py:106` | The `-threads` cap is placed as an input option, so x264 is never capped (verified) |
| M2 | Med | `bot/handlers.py:1377` | The Approve re-check skips `validate_long_script` (missing `[SCREENGRAB]` etc.) |
| M3 | Med | `pipeline/workspace.py:53` | `/render` etc. always take the newest date folder, so starting anything new on a ticker hides the approved work |
| M4 | Med | `pipeline/local_tts.py:56` | The free voice splits "1,234" into "1, 234" and char offsets drift (verified) |
| M5 | Med | `pipeline/youtube.py:41` | The OAuth scopes lack `youtube.force-ssl`, so captions, comments and `/correct` likely 403 |
| M6 | Med | `pipeline/thumbnail.py:588` | A SHORT overwrites the LONG's `thumbnail.png` when both share a folder |

---

## High

### H1. Swapping a clip changes the report, not the video — verified

- **Where:** `bot/handlers.py:1461`, `pipeline/broll.py:1118-1166`,
  `pipeline/render_long.py:2237`, `pipeline/render_long.py:2339`,
  `pipeline/storyboard.py:260`.
- **What happens:**
  - Since the G5 change, the swap menu stores overrides keyed by
    occurrence: `{"CLIP:3": 1}`.
  - `ContentManager.plan()` reads that key, so the approval report and its
    contact sheet show the new take.
  - The LONG renderer still looks overrides up by **payload text**:
    `content.resolve_clip(value, overrides.get(value, 0))`, and
    `resolve_image(..., choice=overrides.get(value, 0))`.
  - So every slot-keyed swap renders take 0.
  - The pre-encode storyboard passes no `choice` at all.
- **Impact:** the operator swaps a clip, re-approves a report that shows the
  new clip, and the paid final ships the old one.
- **Tests:** `tests/test_lanes.py:462` asserts only the contents of the
  override dict, never what the render draws.
- **Direction:** carry each event's swap index onto its cue/segment and look
  up `f"{tag}:{index}"` in the renderer and the storyboard. Keep the payload
  fallback for old workspaces. Add a test that renders after a swap.

### H2. "Sent" is reported even when the send failed — likely

- **Where:** `main.py:90-128`, `bot/handlers.py:1924-1946`,
  `bot/handlers.py:1976-1981`.
- **What happens:**
  - `push_file` in `main.py` schedules `_send()` with
    `asyncio.run_coroutine_threadsafe(...)` and returns immediately.
  - The future is discarded, so any exception from Telegram is never seen.
  - `BotCore.push_file` wraps the call in `try/except`, expecting it to
    raise (the E3 fix). It never does, so it always returns `True`.
- **Impact:**
  - `_finish()` marks `DELIVERY_BACKEND=telegram` deliveries "(sent in chat)"
    even when the upload was rejected.
  - Proof MP4s and storyboards that fail to send produce no warning.
  - There's also no 50 MB check on the video/document path. The cloud Bot
    API rejects uploads over 50 MB, and a full-res proof easily exceeds that.
  - Photos aren't checked against Telegram's dimension limits (tall contact
    sheets).
- **Direction:** have the pusher wait on the future (with a timeout) or
  attach a done-callback that notifies the operator. Check size and
  dimensions before choosing `send_video` / `send_photo` / `send_document`.
- **Same pattern:** `notify()` in `main.py:84` stops at the first chat that
  fails, so the remaining operator chats get nothing.

### H3. 10-K screenshots get paired with the wrong quotes — verified by reading

- **Where:** `pipeline/filings.py:713-727` (`_shoot_blocks`),
  `pipeline/filings.py:838-851` (`auto_filings`).
- **What happens:** `_shoot_blocks` skips any block whose screenshot fails
  and returns a shorter list. `auto_filings` then pairs `raw_shots[i]` with
  `kept[i]` by position.
- **Impact:** after the first failed shot, `filing_02.png` is described with
  quote 1's text, section and "why", and so on down the list. That manifest
  feeds the Step-2 writing prompt and `[SHOW FILING]`. The narration can quote
  one sentence while the screen shows another, under a "FROM THE 10-K" label.
- **Direction:** return results aligned to `located` (`None` for a failure),
  or return `(index, path)` pairs.
- **Related:**
  - `_highlight` marks the first text node that contains the first 30
    characters, which can be in the table of contents.
  - Highlights are never removed between shots, so later shots can show
    earlier yellow marks.
  - `get_by_text(...).first` has the same first-match problem.

### H4. Macro `/headline` shorts cannot be approved in production — verified

- **Where:** `bot/handlers.py:1257-1260`, `bot/handlers.py:1387-1392`,
  `pipeline/gates.py:1776-1782`.
- **What happens:**
  - A macro headline has no workbook, so `data is None` and `as_of=""`.
  - `check_freshness("")` returns a **block** ("the data export carries no
    as-of date") whenever `DATA_STALE_BLOCKS=true`, which is the default.
  - I reproduced this with `Settings(_env_file=None)`.
- **Why the suite misses it:** `tests/conftest.py` sets
  `DATA_STALE_BLOCKS=False` globally. That is why
  `test_macro_intake_is_approvable_without_company_data` passes.
- **Direction:** skip freshness when the format has no company data (the
  macro short is anchored on FRED and the index proxy). Run that test with
  the production default.

### H5. A corrupt ledger resets spend to zero, so the cap fails open — verified by reading

- **Where:** `pipeline/cost.py:80-86`.
- **What happens:** `SpendLedger._load()` returns `{}` on `JSONDecodeError`.
  Month-to-date then reads $0, `reserve_tts_spend` authorises against an
  empty month, and the next `_save()` overwrites the corrupt file. The
  history is gone for good.
- **Impact:** a hand edit, a disk-full write or a stray byte turns the only
  hard stop on spend into no stop. Writes are atomic (tmp + replace), so this
  is rare, but it fails in the expensive direction.
- **Direction:** fail closed. Raise (or refuse paid calls) when the ledger
  can't be read, and keep a `.bak` copy.

### H6. Hosted LLM spend is invisible to the cap — verified by reading

- **Where:** `pipeline/llm.py:198-258`, `pipeline/filings.py:637`.
- **What happens:**
  - Only the filings flagger calls `ledger.record_llm`, and it records a flat
    `FILINGS_LLM_USD_PER_CALL`, which defaults to **0.0**.
  - None of these record anything: the filing brief (many section reads of
    up to ~24k characters each), the skeptic, broll queries, retention notes
    and headline summaries.
  - The default order `ollama,github,openai` means that if Ollama is down
    and `OPENAI_API_KEY` is set, every pass silently becomes paid OpenAI
    usage, with no metering and no cap.
- **Direction:** read `usage` from the OpenAI-compatible response, price it,
  and record it against the ledger (or a separate LLM cap). At minimum,
  refuse the `openai` tier unless a cap is configured.

---

## Medium

### M1. The ffmpeg politeness cap doesn't cap the encoder — verified

- **Where:** `pipeline/render_common.py:103-106` (`run_ffmpeg`).
- **What happens:** `-threads N` is inserted before all of `args`, so it
  lands in front of the first `-i` and becomes an **input decoder** option
  for that input only. x264 picks its own thread count.
- **Reproduced:** with `-threads 1` before `-i`, the x264 SEI reported
  `threads=6` on a 4-core box. After `-i` it reported `threads=1`.
  (`-filter_threads` and `-filter_complex_threads` are global and do work.)
- **Impact:**
  - The README's "workers × threads ≤ budget" isn't true.
  - Parallel segment workers each run x264 at auto threads (about 1.5× the
    cores), oversubscribing the "daily-driver desktop" this is meant to
    protect.
- **Direction:** emit `-threads N` as an output option (just before the
  output path), or add it to `EncodeProfile.video_args()`.

### M2. Approve doesn't re-run the LONG validator — verified by reading

- **Where:** `bot/handlers.py:1356` → `_approval_blockers` at `:1377-1398`.
- **What happens:** the comment (G8) says the re-check catches "a
  `[SCREENGRAB]` file deleted out of `assets/custom/`". That check lives in
  `validate_long_script` (`pipeline/parser_long.py:962`), which is **not**
  re-run, and neither are the cost report's own blockers (the monthly cap).
  Only `run_gates` is.
- **Impact:** an Approve button drawn on an earlier approvable report still
  approves after a screengrab disappears. The cap is still enforced at TTS
  time, so this one costs correctness, not money.
- **SHORTs:** intake runs the gates on `fill_numbers(script, data)`
  (`:1243-1257`), but the approval re-check runs them on the raw `script`.
  The two can disagree (likely).
- **Direction:** share one "blocking findings now" function between intake
  and approve.

### M3. Commands always target the newest date folder — verified by reading

- **Where:** `pipeline/workspace.py:53-58`, used by `render_request`,
  `/upload`, `/why`, `/repurpose`, `/thesis`, `/stillness`, `/batch`,
  `/cancel` (approval withdrawal), `/probe` and others.
- **What happens:**
  - `/short`, `/long`, `/update` or `/headline` on a ticker that already has
    an approved script from an earlier day creates today's folder.
  - `latest_for()` now returns the new, empty folder. `/render TICKER` says
    "no script / not approved" and the approved video can't be reached.
  - There is no way to name a workdate.
  - `latest_for` also doesn't filter on `_DATE_DIR_RE`, which the same module
    defines and uses in `audited_tickers_since`.
- **Related:**
  - `/cancel` withdraws approvals only on the newest folder, not on the
    cancelled job's workdate.
  - `start_lane("long")` (`bot/handlers.py:349`) calls `set_awaiting_angle()`
    unconditionally. Re-running `/long TICKER` the same day wipes the chosen
    angle and re-arms angle mode even when a LONG script exists, which
    defeats the G2 guard in `prompts_reply`.
- **Direction:** prefer the chat's active context, or the newest folder that
  has a script or approval for the format. Accept an optional `@YYYY-MM-DD`.

### M4. The free voice garbles numbers and drifts cues — verified

- **Where:** `pipeline/local_tts.py:56-80`, `:236-241`.
- **What happens:**
  - Sentences over 24 words are split on **every** comma, including
    thousands separators, and rejoined with `", "`.
  - Reproduced: "from 1,234 million" becomes "from 1, 234 million". Piper
    reads "one, two hundred thirty-four".
  - The rejoined piece is no longer a substring of the text, so
    `text.find()` fails, `idx` falls back to `search_from`, and the char
    offsets for the rest of the script drift.
- **Impact:** wrong figures read aloud in `/draft` and `/proof`, and visual
  cues that move.
- **Direction:** split only on `,` followed by whitespace (not between
  digits). Compute offsets from the original slice rather than a rejoined
  string.

### M5. YouTube scopes can't cover captions, comments or corrections — possible (verify against the API docs)

- **Where:** `pipeline/youtube.py:41-45`, `set_captions` (`:333`), `comment`
  (`:347`), `append_description` (`:357`).
- **What happens:** `captions.insert`, `commentThreads.insert` and
  `videos.update` require `youtube.force-ssl` (or `youtube`). The declared
  scopes are `youtube.upload`, `youtube.readonly` and
  `yt-analytics.readonly`.
- **Impact:**
  - Caption and pinned-comment failures are only logged.
  - `/correct` fails outright.
  - There's no script or README step for minting the authorized-user JSON,
    so it's unclear which scopes a real token has.
- **Also:**
  - The "pinned comment" is only posted; the API has no way to pin it.
  - Commenting on a private or scheduled video, which every upload here is,
    probably fails anyway.
  - `/upload` has no duplicate guard, so running it twice makes two private
    videos. (`scripts/backup_state.py` says `published.json` exists "so
    `/upload` does not re-upload", but nothing reads it for that.)
  - `VideoLog.scheduled()` never drops rows whose `publish_at` has passed.
  - `VideoLog.record()` removes and re-appends a row, so after a `/correct`,
    `retention_text`'s `videos[-1]` (`bot/handlers.py:2481`) is no longer
    the latest upload.

### M6. A SHORT overwrites the LONG's cover — verified by reading

- **Where:** `pipeline/thumbnail.py:588-601`, `pipeline/publish.py:39-52`.
- **What happens:** `make_thumbnail` always writes the 16:9 cover to
  `thumbnail.png`, which is the LONG's by-product name. When both lanes
  render into the same ticker/date folder, the SHORT's "noise or signal?"
  cover replaces the LONG's, and `/upload TICKER long` ships it.
- **Also:**
  - Covers are PNG at 1280×720 (and 1080×1920). A rendered room as PNG can
    exceed YouTube's 2 MB thumbnail limit; failures are only logged (possible).
  - For a SHORT, the 3D performer is checked for `9x16` only but also used
    for the 16:9 cover.

### M7. The segment cache can reuse a stale monitor draw-in — likely

- **Where:** `pipeline/segments.py:150-171`, `pipeline/render_long.py:1972-1990`.
- **What happens:**
  - A segment's identity hashes its input files.
  - For the monitor draw-in, the input is an `.ffconcat` **listing**, so the
    hash covers the listing's text (file paths), not the clips it names.
  - `screenin_{i}_room.mov` and `_front.mov` are named by index and rebuilt
    on every render (`reuse=False`).
  - When only the draw-in delay changes (word timings, bumper covers), the
    listing text is identical and a stale cached segment is reused.
- **Direction:** fold the referenced files' stamps into the identity, or name
  the clips by content hash.

### M8. Chapter times are the writer's guesses, used as facts — verified by reading

- **Where:** `pipeline/render_long.py:135-156`, `pipeline/timeline.py:359`,
  `pipeline/publish.py:242`, `templates/master_prompt_long_write.md:437-440`.
- **What happens:**
  - The prompt asks for `mm:ss` that is "approximate, the operator adjusts".
  - No step lets the operator adjust after the voice exists.
  - Those guesses place the chapter openers and their audio cue, the YouTube
    chapter list, and per-chapter retention.
  - With the real ElevenLabs pace, an opener can land mid-sentence in the
    previous chapter.
- **Direction:** anchor each chapter to a text position (an inline marker, or
  the paragraph that opens it) and derive times from word timestamps after
  TTS.
- **Minor:** `_stamp_seconds` and `youtube._seconds` read `mm:ss.f` as
  `h:m:s`.

### M9. The rest of the event loop is still blocked (F2 incomplete) — verified by reading

- **Where:** `bot/handlers.py` glue.
- **What happens:** these still run blocking work directly in the handler
  coroutine:
  - `cmd_edit`, `cmd_replace` and `cmd_undo` run a full intake: the plan,
    which downloads clips, then the gates with the skeptic LLM, then the
    contact sheet.
  - `cmd_headline` runs a URL fetch with an LLM summary, the SEC 8-K, FRED
    and the free news merge.
  - `cmd_prompts` runs a live quote and the news merge.
  - The `fv` veto callback runs `_long_write_reply`, which fetches news.
  - `cmd_thesis` runs the news merge.
  - `cmd_kit` runs the kit doctor.
- **Impact:** `/status`, `/cancel` and render-finished pushes freeze while
  these run, which is exactly what the F2 docstring describes.
- **Direction:** route them through `_off_loop`.

### M10. `/edit` and `/replace` lose line breaks — verified

- **Where:** `bot/handlers.py:932-938`; PTB 22.8 `CommandHandler`
  (`args = message.text.split()[1:]`).
- **What happens:** command args are whitespace-split and re-joined with
  single spaces. The documented multi-line replacement
  (`script_edit.edit_lines`) can't be reached from chat, and a `/replace old`
  that spans a line break or a double space can never match.
- **Direction:** read `update.effective_message.text` and strip the command
  prefix yourself.

### M11. The batch forgets failed renders — verified by reading

- **Where:** `bot/handlers.py:2235-2242`.
- **What happens:** `run_batch` marks an entry done when the job is
  **submitted**. If the overnight render then fails, the entry is gone,
  although `BatchQueue`'s docstring says "nothing expires … the work is
  still here".
- **Direction:** close the entry on job completion, or reopen it on failure.

### M12. Mocked prices can reach a final render — verified by reading

- **Where:** `pipeline/gates.py:1969`, `pipeline/prices.py:106-123`.
- **What happens:** the price gate blocks only `final and not
  settings.mock_mode`. With `MOCK_MODE=false MOCK_PRICES=true`,
  `MockPriceSource` returns fixture or synthetic series with
  `degraded=False`. A final, and its cover monitor, ships invented prices
  unblocked.
- **Direction:** block on `settings.mocking_prices` or `series.source in
  ("fixture", "synthetic")` for finals.

### M13. MOCK runs pollute the real records — verified by reading

- **Where:** `bot/handlers.py:2048` (`_record_thesis`), `_note_confession`,
  `pipeline/corpus.py:165`.
- **What happens:** mock renders pin theses and confession rows exactly like
  real ones, and `Watchlist.all()` adds every thesis ticker. A box that ran
  in MOCK before going live keeps fake theses in `/thesis`, `/update`,
  `/scoreboard` and the intraday watch, because the state directory is shared.
- **Sameness gate:**
  - `build_index` reads every script ever **saved** (abandoned drafts,
    rejected pastes), although the gate's docstring says "against the ones
    already shipped".
  - A draft can block a later video, and drafts push shipped videos out of
    `SAMENESS_WINDOW`.
  - Every macro short uses the `SPY` proxy ticker, so the same-ticker
    exclusion means macro shorts are never compared with each other.

### M14. Retention can delete the only copy of a final — verified by reading

- **Where:** `pipeline/cleanup.py:52-76`.
- **What happens:** `_delivered/` is pruned as "duplicates of what's already
  archived remotely". With `DELIVERY_BACKEND=local` (and in MOCK) it's the
  only copy, and the workspace MP4s are pruned too.
- **Also:**
  - `cache/` is never pruned: TTS, segments, 3D Dennis PNG frames **and**
    PNG-codec `layer.mov` per shot, and broll.
  - `state/jobs/*.json` is never pruned.
  - `PRUNE_DIR_NAMES` omits `render_long_proof` and `render_long_preview`.
    Their videos go by suffix, but the PNGs and other files stay.
  - Both grow without bound, and `JobStore.all()` reads every job file on
    each `/status` and `submit`.

---

## Low / edge cases

**Job queue (`pipeline/jobs.py`, `bot/handlers.py:1573`)**
- `checkpoint()` in the worker thread and `/cancel` on the loop both do
  load→modify→save on the same job file. A checkpoint can write RUNNING back
  over a fresh CANCELLED (lost update).
- Job JSON writes aren't atomic. `/status` and `submit()` can read a
  half-written file, skip it, and allow a duplicate submit.
- Drafts and proofs set `job.delivered_link` on the in-memory job. The worker
  reloads from disk afterwards, so the link is dropped.
- A cancel that arrives during delivery, after the upload, reports
  "cancelled" though the video was delivered and the thesis recorded.

**TTS (`pipeline/tts.py`)**
- After stitching, chunk MP3s and their sidecars are deleted (`:571`)
  **before** `ffprobe_duration(audio)` runs and `words.json` is written
  (`:585`). If that window fails, `audio.m4a` exists without `words.json`:
  it isn't a cache hit and the paid chunks are gone, so the next run pays
  again. Write `words.json` first.
- `record_cache_hit` fires on every paid-tier hit, including `/repurpose`
  (`cached_only`) and re-renders, so "the cache saved $X" is inflated.
- Chunk resume is keyed by index only. Changing `TTS_CHUNK_CHARS` between a
  failed run and the retry stitches mismatched audio.
- There's no retry or backoff on ElevenLabs 429/5xx; the job fails and needs
  a manual re-run (resume works).
- The budget check uses the clean text, while billed text includes the
  inserted delivery tags. The cost estimate uses `char_count`, so it's
  slightly low.

**Long render**
- `composite_video` has a fixed 2 h timeout (`render_common.py:630`). The
  LONG final is x264 `slow`, CRF 18, `aq-mode=3`, delivered at 1440p, on
  half the cores at `nice 10`. A 40-minute cut can plausibly exceed that
  after the voice has been paid for. Scale the timeout with duration.
- `performer.close()` (`render_long.py:2436`) isn't in a `try/finally`. An
  exception in the segment loop leaves the Blender worker until GC closes
  its pipes.

**3D Dennis (`pipeline/dennis3d.py`)**
- `_ask` blocks on `for line in proc.stdout` with no timeout. A hung Blender
  stalls the render worker indefinitely, and `/cancel` can't reach it.
  `proc.wait(timeout=30)` raises `TimeoutExpired`, not `RenderError`.
- Cost: per-frame Cycles at 12 fps. The proof and the final each redraw
  every shot. There's no estimate or warning before queueing; a LONG with
  `DENNIS_3D=on` can hold the single worker for many hours.
- `_start` reopens `worker.log` without closing the previous handle.
  `_has_bpy` caches `False` for the life of the process.

**ffmpeg path and quoting**
- Bare `"ffmpeg"` is used instead of `detect_ffmpeg()` in
  `dennis3d.extent` (`:286`), `render_short.render_frames` (`:1527`) and
  `render_short._has_encoder` (`:1258`). The configured FFmpeg path is
  ignored, and the short's frame pipe isn't niced or capped.
- If ffmpeg dies mid-pipe in `render_frames`, `BrokenPipeError` propagates
  and ffmpeg's stderr is never shown.
- `_run_polite` decodes stderr as strict text, so non-UTF-8 bytes raise
  `UnicodeDecodeError` and mask the real error.
- `software_equivalent()` drops `tune`, `x264_params` and the BT.709 tags.
- Subtitle filenames and concat-list paths aren't escaped for `'`, `:` or
  `\` in `composite_video` / `concat_audio` (`render_short.final_encode`
  does escape).

**Upload intake (`bot/handlers.py`)**
- `_looks_truncated` (`:851`) only refuses fragments of about 4,096
  characters. The **last** fragment of a split paste is shorter, passes,
  and can be saved over the good script.
- `[SCREENGRAB]` captures go to a shared `assets/custom/<slug>.*`.
  - Slugs are global across tickers.
  - Re-uploading with another extension leaves both files, and the first
    one the glob finds is used.
- `on_document`: the cloud Bot API caps downloads at 20 MB. A larger
  screengrab clip fails with a bare "internal error".
- `on_photo` saves Telegram's compressed JPEG as `.png`. A photo (as
  opposed to a file) can never satisfy a `[SCREENGRAB]` slug.
- A CSV upload that won't be read (because an `.xlsx` is present) still
  withdraws approvals.

**Bot commands**
- `_upload_pair` always says "the second failed", even when the first fails
  (`:2427`). `/upload clip` always sends `clips[0]`.
- Re-running `/repurpose` after a re-render that yields fewer windows leaves
  stale `short_repurposed_N.mp4` files that `/upload clip` and
  `/upload pair` will pick up.
- `/watch` and `/batch` accept any word as a ticker; `/watch list` watches
  "LIST".
- `_send` drops the keyboard when the reply text is empty.

**Workspace (`pipeline/workspace.py`)**
- Re-intake of identical text (swap, "back to report", undo) pushes
  duplicate revisions, so `/undo` steps through identical copies.
- Revision files are named `{n:03d}` and sorted as strings, which breaks at
  1,000 revisions.
- `approved_sha` and `broll_overrides` call `json.loads` unguarded.
- Script, approval and state JSON writes aren't atomic.

**Compose and moves**
- `compose.build_layers`: `(shot.part == 2 and _move_in(...)) or
  _focus_placement(...)` falls back to the full close-up exactly when
  `_move_in` rejected it for slicing a neighbour. `punch_in_slot` and
  `build_layers` validate against different stage boxes.
- `moves._zoom_lands_under_caption` (fdf5bce) checks only the fully pushed-in
  end state; a line can travel under the caption during the push.
  `_zoom_cuts_a_line` uses the **unclamped** view box while the new check
  clamps "as the renderer clamps", so the two disagree near edges.

**Kit**
- 46544f6 patched the vendored `kit/engine/grounds.js` in place ("the same
  patch goes to design"). The next wholesale `kit/` swap will silently
  revert it, and no test pins the y-axis-label behaviour. Keep local patches
  as a patch applied at ingest, or add a regression test.

**Delivery (`pipeline/delivery.py`)**
- The `drive.file` scope only sees files this app created, so a hand-made
  `GDRIVE_ROOT_FOLDER_ID` likely 404s.
- Service accounts have no storage quota outside Shared Drives.
- Folder names aren't quote-escaped in the Drive query.
- The MP4 is uploaded as `application/octet-stream`, so there's no preview.
- The upload is a single PUT with no resume, and re-delivery creates
  duplicates.

**Gates and scheduling**
- `check_freshness` accepts a future-dated as-of without comment.
- `in_batch_window` with start == end (e.g. 0/24) is never open.
- `BatchQueue.clear()` reports the count including done rows.
- `parse_cron` silently ignores the day-of-month and month fields.

**Other**
- `room_dressing.episode_number` assigns the same number to two LONGs
  rendered before either is uploaded, and renumbers on out-of-order upload.
- `_finish_filing_read` reports a reading that **raised** as "has not
  finished — re-upload once it lands". `_filing_reads` entries leak when no
  upload follows.
- `standing.Move.change` returns 0 when the pinned value is 0. A thesis
  number that started at zero (e.g. net income) can never register a move,
  however far it goes.
- `scripts/make_score.py` uses check-then-act `would_exceed` rather than
  `reserve_tts_spend`.
- `filings.fetch_and_summarize` (`:574`) sends `SEC_USER_AGENT`, which SEC
  asks to carry a contact email, as the User-Agent to arbitrary news sites
  pasted into `/headline`.
- `bot/prompts.fill_prompt` substitutes tokens one after another into one
  string. Scraped text (news, article summaries, filing quotes) lands in the
  prompt the operator pastes into Claude unescaped, and a later token's
  placeholder inside that text would be replaced too. This is low risk
  because the operator reads the output, but it is an injection path.
- Config: `env_file=".env"` is relative to the current directory. Scripts run
  from elsewhere silently fall back to defaults; this is safe (MOCK on), but
  confusing.

---

## Improvements (not bugs)

- **CI is permanently red by design.** `audio_provenance` fails on every
  fresh checkout, and the workflow doesn't deselect it, so a new regression
  doesn't change the badge. Run the gate as a separate step that may fail,
  and keep the suite job on `-m "not audio_provenance"`.
- **The suite's global `DATA_STALE_BLOCKS=False`** hides production-default
  behaviour (H4). Run the intake and approval tests at least once with
  defaults.
- **One "what will render" model.** H1, M2 and the SHORT re-check all come
  from the report, the approval re-check and the renderer each computing
  the same thing their own way. A single resolved plan, stored at approval
  and read by the renderer, would remove the whole class.
- **Fail closed on money paths** (H5, H6). Prefer refusing paid work over
  degrading to "unknown = $0".
- **Chapters from measurements** (M8). Anchor chapters to text and derive
  times after TTS.
- **Cache and state hygiene** (M14). Add an LRU or age prune for `cache/`
  (3D frames especially) and `state/jobs/`.
- **3D Dennis budget.** Before queueing, estimate wall-clock time from
  `perform.py --bench` and show it on the report. Reuse the proof's frames
  when the words haven't changed.
- **Covers as JPEG** (quality around 90) so they always fit YouTube's 2 MB
  limit.
- **Shared ffmpeg runner.** Route every ffmpeg spawn (the frame pipe, probes,
  `extent`) through `render_common` so path, niceness, thread caps and
  error capture are uniform.
- **Static analysis.** `ruff --select B023` flags 63 closures defined inside
  `render_long`'s segment loop. They're called within the same iteration, so
  they're correct today, but one stored or deferred call would bind the last
  segment. Consider hoisting them or binding defaults.
- **Document how to mint the YouTube token** (the scopes in M5), or ship a
  small `scripts/youtube_auth.py`.

---

## Test suite and static analysis

**ruff** (`F, E9, B, PLE, PLW, ASYNC` over `bot`, `pipeline`, `scripts`,
`room3d`, `config.py`, `main.py`):

- **Correctness rules (`F`, `E9`, `PLE`):** only one unused import
  (`compose.py:1777`).
- **Blocking file I/O in async handlers:** `main.py:107/117`,
  `bot/handlers.py:3128/3131`. Small files; noted only.
- **B023:** see Improvements.

**Full suite:** see the section appended below.
