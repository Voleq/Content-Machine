# Workflow and command suggestions

The bugs and improvements this file used to list are fixed (commit
`795ebe6`, with one regression test per finding in
`tests/test_review_fixes.py`). This page now holds proposals only. Nothing
below is implemented.

---

## The problem

The bot answers **47 commands**. A normal day uses about ten of them: start a
video, upload the workbook, paste, approve, render, upload. The other
thirty-seven are reading tools (retention, lines, hooks, scoreboard…) and
admin.

They all live in one flat list. That list shows up in three places that are
kept in sync by hand: `/help`, the README table, and the Telegram menu.
Similar commands differ by one word (`/render`, `/render_long`,
`/render_short`, `/draft`, `/proof`, `/repurpose`). Most of them also need
the ticker typed again, even though the chat already knows which video you
are working on.

---

## 1. Group the commands into nine families

Keep every old name working as a hidden alias for one release. Muscle memory
keeps working, and `tests/test_docs.py` can move over in one change.

| New command | Subcommands | Replaces |
|---|---|---|
| `/new` | `short` · `long` · `update` · `headline` + TICKER | `/short` `/long` `/update` `/headline` (keep `/short` and `/long` as shortcuts, since they are daily) |
| `/script` | *(show)* · `edit N …` · `replace a => b` · `undo` · `why …` · `prompts` | `/script` `/edit` `/replace` `/undo` `/why` `/prompts` |
| `/render` | *(final, the default)* · `draft` · `proof` · `clips` + `short`/`long` | `/render` `/render_long` `/render_short` `/draft` `/proof` `/repurpose` |
| `/publish` | *(upload)* · `pair` · `probe` · `scheduled` · `correct …` | `/upload` `/probe` `/scheduled` `/correct` |
| `/jobs` | *(status)* · `cancel` · `batch [add\|run\|clear]` | `/status` `/cancel` `/batch` |
| `/ideas` | *(backlog)* · `add` · `drop` · `screen [lane]` · `watch` · `earnings` · `thesis` | `/ideas` `/idea` `/unidea` `/screen` `/watch` `/earnings` `/thesis` |
| `/stats` | `retention` · `lines` · `shots` · `stillness` *(one video)*; `hooks` · `rules` · `runtime` · `lessons` · `experiments` · `scoreboard` *(the channel)* | ten commands |
| `/search` | *(ask the AI)* · `find` · `said` | `/ask` `/find` `/said` |
| `/admin` | `cost [explain\|reconciled]` · `kit doctor` | `/cost` `/kit` |

That is nine families plus `/help [family]`. The Telegram menu
(`setMyCommands`, scoped to the operator chats) would list only these nine.
Typing `/` then shows a short menu instead of a wall of commands.

---

## 2. Stop asking for the ticker

Every command could default to the chat's active video (`ActiveContext`
already tracks it). The ticker, or `TICKER@YYYY-MM-DD` (which the resolver
now understands), becomes an override rather than a requirement:

```
/render            → the video you are working on
/render proof      → same, as a $0 proof
/render AAPL       → another one
```

Every reply should then say which video it acted on. The `(from
YYYY-MM-DD)` suffix that `/render` now adds is the start of that.

---

## 3. One "video card" per video, edited in place

Instead of a new message at every stage, keep one message per video and edit
it with `edit_message_text` as things change:

```
📁 AAPL · LONG · 2026-10-05
data      ✅ as of 2026-10-03
script    rev 4 · 9,812 chars · gates ✅ · 2 warnings
approval  ✅ (sha 3f9a…)  · est. $1.94 · ~38 min
renders   draft ✅ · proof ✅ · final ⏳ 12/31 segments
upload    —
[Edit] [Proof $0] [Render 💰] [Cancel]
```

This replaces "what state is this in?" polling with `/status`, `/script` and
`/stillness`. It also puts the next action one tap away. Progress pushes
("render 5/10 segments") update the card instead of adding messages.

---

## 4. Next-step buttons at each handoff

The flow has a fixed shape, so each reply can offer the obvious next taps:

| After | Buttons |
|---|---|
| workbook upload | **Get prompt** · Re-upload |
| angle prompt | the ranked angles as buttons (instead of typing a number) |
| report | **Approve ✅** · Swap clip 🔄 · Edit ✏️ · Cancel |
| approve | **Draft $0** · **Proof $0** · **Render 💰 ~$1.94** |
| final delivered | **Upload private** · Schedule… · Cut clips |
| upload | **Retention** (enabled after 48 h) · Correct… |

Spend buttons should carry the estimate and need a second tap:
"Render LONG — ~$1.94, ~38 min [Confirm]". That puts the money moment where
the eye already is.

---

## 5. A daily inbox

One morning message (it could ride on the screener digest) listing
everything that is waiting on you:

- scripts with a report and no approval
- approved scripts not rendered
- finished renders not uploaded
- scheduled publishes in the next 48 h
- retention ready to read for videos that are 2+ days old
- batch entries that failed overnight (the batch now reopens these)

Today each of these needs its own command to find out.

---

## 6. Guided flow for the daily SHORT

A `/go TICKER` wizard that walks the short end to end with Telegram
`ForceReply` prompts:

> workbook? → prompt → paste → report → approve → render → upload when done?

You stay in one thread, and the bot asks for exactly the next thing. The
LONG keeps its two manual Claude steps, but the angle pick becomes buttons
(section 4).

---

## 7. One command registry, generated everywhere

Define each command once:

```python
Command("render", group="render", handler=..., usage="[TICKER] [draft|proof|clips] [short|long]",
        help="render the approved script (or a free pass)", off_loop=True,
        aliases=("render_long", "render_short", "draft", "proof", "repurpose"))
```

The PTB handlers, `HELP_TEXT`, `/help family`, `setMyCommands` and the README
command table would all be generated from that list. `tests/test_docs.py`
then checks one source instead of two directions.

Defaulting `off_loop=True` also prevents the "blocking call on the event
loop" class of bug (review item M9) from coming back.

---

## 8. Smaller things

- **"Did you mean…"** on an unknown command or a malformed one, using
  `difflib` against the registry. Today a typo gets silence or a bare usage
  line.
- **Notification level:** `/admin quiet` keeps only finished, failed and
  needs-you. The default stays verbose.
- **A publishing calendar:** `/publish scheduled` drawn as a week view, with
  gaps highlighted, so batch planning has something to plan against.
- **Undo for `/jobs cancel`** within a minute, since a cancel also withdraws
  the approvals.
- **Per-family help** that shows real examples with your active ticker filled
  in.

---

## Suggested order

1. **Registry, families and aliases, plus the trimmed Telegram menu**
   (sections 1, 2, 7). This is mechanical, invisible to existing habits, and
   makes everything after it cheaper.
2. **Video card and next-step buttons** (sections 3, 4). This is the biggest
   day-to-day win.
3. **Inbox and SHORT wizard** (sections 5, 6), once the card exists to link
   to.
