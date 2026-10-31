# Workflow and command suggestions — status

The bugs this file first listed were fixed in `795ebe6` (one regression test
per finding in `tests/test_review_fixes.py`). The workflow proposals that
replaced them are now built. This page records what was built, where, and
where it differs from the proposal. Tests: `tests/test_workflow.py`.

| # | Proposal | Status | Where |
|---|---|---|---|
| 1 | Nine command families, old names as hidden aliases | ✅ `/new` `/script` `/render` `/publish` `/jobs` `/ideas` `/stats` `/search` `/admin`, plus `/go` `/card` `/inbox` `/help`. All 47 old names still answer. The Telegram menu lists the 13 entry points only. | `bot/commands.py` |
| 2 | Stop asking for the ticker | ✅ A command that takes a ticker falls back to the chat's active video and says which one it used (`📁 EXMPL 2026-10-05`). `TICKER@YYYY-MM-DD` names an older folder. Free-text commands only treat the first word as a ticker when that ticker has a workspace. | `_fill_ticker` in `bot/commands.py` |
| 3 | One video card per video, edited in place | ✅ `/card [TICKER]`. Each card message is remembered and edited as its jobs move (throttled to one edit per 10 s while a render progresses). | `pipeline/video_state.py`, `CardBoard` |
| 4 | Next-step buttons at each handoff | ✅ Angle picks, Edit on the report, Draft/Proof/Render after Approve, Upload/Schedule/Cut clips when a render lands, Render final after a proof, Retention/Correct after an upload. **Render asks once more**, with the price and the month so far. | `bot/keyboards.py`, `handle_callback` |
| 5 | A daily inbox | ✅ `/inbox`, also sent at `INBOX_HOUR` when it is not empty. | `inbox()` in `pipeline/video_state.py` |
| 6 | Guided flow for the daily SHORT | ✅ `/go TICKER`: workbook → paste → approve → render → upload, with the next step written under each reply. Leaving the wizard at any point is fine. | `WIZARD` in `bot/commands.py` |
| 7 | One command registry, generated everywhere | ✅ The Telegram handlers, `/help`, `/help FAMILY`, the menu, the README command reference (`python -m bot.commands --readme`, checked by `tests/test_docs.py`) and the web panel all come from it. Command bodies run off the event loop by default. | `bot/commands.py` |
| 8 | Smaller things | ✅ "Did you mean…", `/admin quiet`, `/publish calendar`, `/jobs undo` (a cancel can be undone for a minute), per-family help with your ticker filled in. | `bot/commands.py` |
| — | A panel that uses every command | ✅ The web panel. It runs every registry command, button, paste and upload through the same code as the chat, and adds the inbox, video cards, queue, spend, an activity feed, uploads past 20 MB and in-page video playback. | `bot/panel.py`, `bot/panel_static/` |

## Where it differs from the proposal

- A typed `/render` still queues straight away. Typing it is the deliberate
  act. Only the buttons ask twice, because a tap is easy to make by accident.
- The angle buttons always offer three angles. The bot never sees the model's
  angle list, and the prompt asks for two or three.
- The menu has 13 entries rather than 9, because `/go`, `/card` and `/inbox`
  are where a session starts.

## Not done

- No calendar *editing*. The calendar shows the week and marks the gaps, but
  scheduling still goes through `/publish … YYYY-MM-DD HH:MM` or the
  Schedule… button.
- The panel's chat identity is a single chat (`PANEL_CHAT_ID`). Two
  operators using the panel at once share one active video.

## Second review of the bot (31 Oct 2026)

A full read of `bot/` (the Telegram glue, `BotCore`, the commands, the
prompts, the panel and its page) and the pipeline code it drives. Each fix
has a regression test in `tests/test_bot_review.py` that failed before it.

| Found | Fixed in |
|---|---|
| python-telegram-bot hands edited messages to every handler by default: editing an old `/render XYZ` queued the paid render again, and an edited paste re-ran the intake or answered a question asked since | `build_application`: only new messages |
| The Cancel 🚫 that stops a render (`j\|`, `jx\|`) waited behind a slow upload; only the report's Cancel (`x\|`) skipped the line | `is_queue_control` |
| A LONG's contact sheet over Telegram's photo limits (about 150 visuals) was sent as a photo and refused after the report's text had gone | `_ship` sends it as a file (`fits_photo`) |
| The overnight batch's report and the weekly note stopped at the first operator chat that failed, and never reached the page's Activity | `_tell_operators` |
| `/jobs batch run` and the overnight window planned the batch on the event loop | `run_batch` |
| A mover whose % change read as "-" raised in `/movers` and showed as +0.0% on Home | `stockanalysis.tradeable`, one `MOVER_LISTS` for both |
| The earnings calendar was cached under "today" for six hours, so after midnight it was yesterday's | keyed on New York's date (`_market_day`) |
| With stockanalysis.com down, every part of a gather waited out its own timeout on every upload and `/prompts` | `_raw_get` leaves the site alone for five minutes after a timeout, 429 or 5xx |
| A lane-less folder's angle prompt was made from a SHORT's site pack (no year-ago call) | `prompts_reply` |
| An angle pick parsed the workbook three times | `_long_write_reply` takes the caller's data |
| The SHORT prompt listed each of the site's stories twice, and its eight headline slots went to them | `why_it_moved_block`, `move_kind.HEADLINES_KEPT` |
| `/site` printed UTC read times with no zone beside coverage in New York time; the page did the same | `_local_stamp`; the page's `when()` |
| Two threads saving `chat_state.json` or `active_context.json` at once lost one chat's change | locks on `ChatState` and `ActiveContext` |
| The page's chat.js redefined the global `copyText`: every copy button in a video's workspace came back reading "Copy" | one `copyText` (video.js) |
| A restarted bot counts its feed from one again, so the page missed the new run's first pushes | the feed's `epoch` |
| The Check step's Save why sent no ticker: a reason starting with another video's ticker was saved there, first word gone | sends `TICKER@DATE` |
| The page priced Render buttons when the voice was already paid for | `_step_approve`, `_step_render` |
| A question asked on the page's chat while another was being answered had no place in line until that answer was done (the worker rebuilt the order between answers only); CI caught it as an intermittent `KeyError: 'ahead'` | `Chats._join_line`, the order built under the chat lock |

## Review of everything outside the bot (31 Oct 2026)

`pipeline/`, `config.py`, `scripts/`, `room3d/`, `deploy/` and the kit's
engine, after the bot's. Each fix has a regression test in
`tests/test_pipeline_review.py` that failed before it.

| Found | Fixed in |
|---|---|
| The thesis book never tracked revenue: it pinned `revenue_ltm`, which no sheet carries, so a 30% fall in the number most videos are about could not move a thesis | `standing.DEFAULT_TRACKED`: `revenue`, the History sheet's LTM |
| A margin was judged as a share of itself: half a point on a 10% margin was material and pushed as "gross_margin ↑5%", a margin from -2% to 1% read "↑150%", and the scoreboard printed a four-point fall as "-6%" | `standing.Move` measures rates in points (material at 3); `scoreboard` prints through `Move` |
| An after-the-close print became "the numbers are out" only the next day, so the alert meant to go out fast arrived at nine the next morning | `EarningsCalendar.due_alerts`: `amc` flips at 16:30 New York |
| Before the open, yesterday's whole-day volume was announced as "3.0× normal volume — something is going on" every morning | `alerts.evaluate` leaves the volume alone until the open, as it did the price |
| Every headline in the window decided the kind of day, naming the company or not: "Nvidia Q3 earnings beat" in META's feed cut META's short as an earnings reaction | `move_kind.classify(names=…)`: the headlines naming it and its own 8-K and IR feeds decide; the prompt marks the rest |
| The voice lint suggested trailing zeros: "twelve point three zero percent", "five point zero zero billion dollars" | `spoken._spoken` |
| A card's per-share figure (`$1.20`) and multiple (`12.0x`) were never heard by the move planner, so their count-up and pen-circle went off when the shot opened instead of on the word | `moves._said_forms` listens for the spoken form, the plain decimal and the digits |
| The morning screen and the intraday alerts stopped at the first operator chat that failed; the screen was then never marked sent and went again on every restart, and neither reached the page's Activity | `screener` through `_tell_operators` |
| Theses, ideas, the overnight batch, confessions, the watchlist, the alert log, the earnings calendar, the used jokes and the upload record were each read whole and written whole from more than one thread, and the second write lost the first | one lock in `standing` (`locked`), `VideoLog._lock` |
| A correction read the upload's row, posted to YouTube, then wrote the row back over the retention pulled meanwhile | `VideoLog.update` (`pin_correction`, `/publish mark`) |
| The alert files were rewritten in place: half a file read as nothing said (everything alerted again) or an empty watchlist | write-then-rename |
| B-roll clips, pictures, memes and 10-K downloads were written straight to their cache names, so one cut short was a cache hit for every later render; a repurposed clip cut short was counted as a clip | part file, then rename (`broll.normalize_clip`, `save_whole`, `filings._write_whole`, `repurpose._cut_window`) |
| `get_price_history` never raises, by contract, and a full disk raised out of its last line into the price gate and the chart | `prices._keep` |
| A 429 whose `Retry-After` was a date failed the voice job | `tts._retry_after_s` |
| `/kit doctor` took twelve seconds walking every slot of the library once per plate, and read the renderer from the working directory | `gates.reachable_plates`: once, beside the code (0.4 s, the same routes) |
| The used-jokes check re-read the book and re-split every joke for every sentence: four seconds at a thousand jokes, growing with every video | `JokeBook.index` |
| Filing and IR excerpts kept `&#8220;`, `&mdash;` and the rest as written | `sources._strip_html` (`html.unescape`, apostrophe kept plain) |
| A yield or ownership share written as text ("1.5%", a CSV) read as 1.5, a 150% yield | `company_data._as_fraction` |
| The company's name was matched as letters: "Metals rally" was a headline about Meta | `CompanyData.names_company` |

Three older tests changed with the fixes. `test_standing.py` built margins
as fractions (0.40) where the History sheet holds percents (58.0), and pinned
the relative wording; `test_receipts.py` pinned the scoreboard's own
formatter, which disagreed with `Move` about the same row (-31% against its
0.4 → 0.28); `test_alerts.py`'s market-day test now uses a print with no time
given, which keeps what it guards (the UTC rollover) without the `amc` rule.

### Looked at, and left

- Hardlinking local deliveries to save the second copy: `/repurpose` rewrites
  a clip in place, which would change the delivered one too.
- A `[` inside a plate's text ends the tag early; the direction gate blocks
  the leftover, though its message says the tag is not closed.
- `chunk_text` cuts mid-word only in a paragraph over 4,000 characters with no
  sentence end. The MP3 chunks' timing was measured: about 20 ms over nine
  chunks, under a frame.
- The volume alert compares the day's volume so far with a whole day's
  average, so it is slow to fire early in the session; a calibration choice.
- `$-5M` is not flagged and only the top of a range ("5-10%") is suggested.
- The Telegram menu is set chat by chat with no retry per chat (cosmetic).

### How deep

Read line by line: the gates, both parsers, the models, the job queue, the
workspace and video state, the screener, alerts, the standing state, channel
memory, recall, retention, the corpus, cost, TTS, YouTube, delivery,
publishing, cleanup, the sources, the company data loader, filings and the
filing brief, prices, the kind of day, spoken figures, tagging and the short's
data. The render side (`render_*`, `compose`, `moves`, `plates`, `timeline`,
`broll`, `memes`, `dennis3d`), `room3d/`, `deploy/` and `scripts/` were read
for their I/O, processes, caches and failure paths; the kit's engine through
its own audit (30 of 30 runnable rules pass, 3 wait for data by design).
