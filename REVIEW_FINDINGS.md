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
