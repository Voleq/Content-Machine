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
