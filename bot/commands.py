"""Every command the bot answers, defined ONCE.

The bot grew to forty-seven flat commands, kept in sync by hand in three
places — the `/help` text, the README table and the Telegram menu — and most
of them asked for the ticker the chat already knew. This module is the one
list. From it come:

- the Telegram handlers (`telegram_names`, `run_command`),
- `/help` and `/help FAMILY` (`help_text`, `family_help`),
- the Telegram "/" menu (`menu_commands`),
- the README's command reference (`readme_markdown`; `tests/test_docs.py`
  fails when the README's copy is stale),
- the web panel's command list (`registry_json`).

The commands are grouped into families — `/new`, `/script`, `/render`,
`/publish`, `/jobs`, `/ideas`, `/stats`, `/search`, `/admin` — plus the
three workflow entry points `/go`, `/card` and `/inbox`. Every old name
(`/short`, `/draft`, `/upload`, …) still works as a hidden alias.

A command that takes a ticker defaults to the chat's ACTIVE video when you
leave it out, and says which video it acted on.

Every command body runs off the event loop unless it is a coroutine (which
then does its own blocking work in a thread): a slow command can never
again freeze `/status`, `/cancel` and the render-finished push (M9).
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from bot.handlers import _TICKER_RE, BotCore, Reply
from bot import keyboards as kb
from pipeline.workspace import Workspace, _write

log = logging.getLogger(__name__)

Say = Callable[[Reply], Awaitable[None]]


# --------------------------------------------------------------------------
# The shapes.
# --------------------------------------------------------------------------


@dataclass
class Call:
    """One invocation: who, with what. `raw` is the message text after the
    command word(s), verbatim — line breaks and all (M10)."""
    core: BotCore
    chat_id: int
    args: list[str]
    raw: str = ""
    say: Say | None = None
    filled: str = ""       # "TICKER YYYY-MM-DD" when the active video stood in

    async def tell(self, text: str) -> None:
        if self.say is not None:
            await self.say(Reply(text))


@dataclass(frozen=True)
class Family:
    name: str
    title: str
    blurb: str                    # one line: /help and the Telegram menu
    notes: str = ""               # README prose under the family's table


@dataclass(frozen=True)
class Command:
    family: str
    sub: str                      # "" for the family's default
    usage: str                    # what follows the name
    help: str                     # one line, for /help
    run: Callable
    doc: str = ""                 # the README cell; `help` when empty
    aliases: tuple[str, ...] = ()
    # How a missing ticker is filled from the active video:
    #   ""         the command takes no ticker
    #   "optional" a ticker is optional and NOT filled (no ticker means
    #              something: every video, the whole list)
    #   "plain"    filled with TICKER
    #   "dated"    filled with TICKER@YYYY-MM-DD — that exact folder
    #   "text"     free text follows; filled unless the first word is a
    #              ticker that has a workspace
    ticker: str = ""
    ack: str = ""                 # said before a slow command starts
    example: str = ""             # "{T}" is the active ticker
    spends: bool = False

    @property
    def name(self) -> str:
        return f"{self.family} {self.sub}".strip()

    @property
    def slash(self) -> str:
        return f"/{self.name}"

    @property
    def line(self) -> str:
        return f"{self.slash} {self.usage}".strip()


# Words that are never a ticker, so `/render proof short` does not try to
# render a stock called SHORT and a missing ticker is noticed.
KEYWORDS = {
    "short", "long", "clip", "clips", "pair", "again", "draft", "proof",
    "final", "all", "now", "drop", "remove", "off", "on", "list", "show",
    "ls", "run", "clear", "add", "reconciled", "reconcile", "explain",
    "where", "breakdown", "doctor", "report", "trending", "value", "bmo",
    "amc", "quiet", "verbose", "loud",
}


def looks_like_ticker(token: str) -> bool:
    return (bool(token) and token.lower() not in KEYWORDS
            and bool(_TICKER_RE.match(token.upper()))
            and any(ch.isalpha() for ch in token.split("@")[0]))


def _has_workspace(core: BotCore, token: str) -> bool:
    if not looks_like_ticker(token):
        return False
    ticker, _ = Workspace.split_arg(token)
    return bool(Workspace.dates_for(core.settings, ticker))


def _reply(x) -> Reply:
    if isinstance(x, Reply):
        return x
    return Reply("" if x is None else str(x))


# --------------------------------------------------------------------------
# Per-chat state: the /go wizard, and the question a button just asked.
# --------------------------------------------------------------------------


class ChatState:
    """`state/chat_state.json`: per chat, the wizard's step and any answer a
    button is waiting for ("reply with the time to schedule it")."""

    PENDING_TTL_S = 15 * 60

    def __init__(self, settings):
        self.path = Path(settings.state_dir) / "chat_state.json"

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _chat(self, chat_id: int) -> dict:
        return self._load().get(str(chat_id), {}) or {}

    def _put(self, chat_id: int, key: str, value) -> None:
        data = self._load()
        entry = data.get(str(chat_id), {}) or {}
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
        data[str(chat_id)] = entry
        _write(self.path, json.dumps(data, indent=2))

    # the wizard
    def wizard(self, chat_id: int) -> dict:
        return self._chat(chat_id).get("wizard") or {}

    def set_wizard(self, chat_id: int, ticker: str, workdate: str,
                   step: str) -> None:
        self._put(chat_id, "wizard", {"ticker": ticker, "workdate": workdate,
                                      "step": step})

    def end_wizard(self, chat_id: int) -> None:
        self._put(chat_id, "wizard", None)

    def wizards(self) -> dict[int, dict]:
        out = {}
        for k, v in self._load().items():
            if isinstance(v, dict) and v.get("wizard"):
                try:
                    out[int(k)] = v["wizard"]
                except ValueError:
                    continue
        return out

    # a question a button asked
    def pending(self, chat_id: int) -> dict:
        p = self._chat(chat_id).get("pending") or {}
        if p and time.time() - float(p.get("at", 0)) > self.PENDING_TTL_S:
            self._put(chat_id, "pending", None)
            return {}
        return p

    def ask(self, chat_id: int, kind: str, **data) -> None:
        self._put(chat_id, "pending", {"kind": kind, "at": time.time(), **data})

    def answered(self, chat_id: int) -> None:
        self._put(chat_id, "pending", None)


class NotifyPrefs:
    """`/admin quiet`: keep only finished, failed and needs-you pushes."""

    LOUD = ("✅", "❌", "⛔", "⚠️", "🚫", "📥", "💥", "❗", "🧭")

    def __init__(self, settings):
        self.path = Path(settings.state_dir) / "notify.json"

    def level(self) -> str:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get(
                "level", "verbose")
        except (OSError, ValueError, AttributeError):
            return "verbose"

    def set(self, level: str) -> None:
        _write(self.path, json.dumps({"level": level}))

    def wants(self, text: str) -> bool:
        if self.level() != "quiet":
            return True
        return (text or "").lstrip().startswith(self.LOUD)


# --------------------------------------------------------------------------
# The wizard (/go): one SHORT, workbook to YouTube, one thing at a time.
# --------------------------------------------------------------------------

WIZARD = {
    "workbook": "🧭 Step 1/5 — refresh the attached workbook and send it "
                "here as dennis_data.xlsx.",
    "paste": "🧭 Step 2/5 — run prompt_short.md in Claude and paste the "
             "script back here (or send it as a .txt).",
    "approve": "🧭 Step 3/5 — read the report. Approve ✅ when it reads "
               "right; Edit ✏️ when it doesn't.",
    "render": "🧭 Step 4/5 — tap Render 💰 (it asks once more before "
              "spending), or Proof $0 to look at it first.",
    "rendering": "🧭 Rendering — I'll come back with the upload buttons when "
                 "it's done.",
    "upload": "🧭 Step 5/5 — upload it: private now, or schedule it.",
    "done": "🧭 Done. /inbox shows what's waiting next.",
}


def _wizard_step(core: BotCore, chat_id: int, ticker: str, workdate: str,
                 step: str, reply: Reply) -> Reply:
    """Move this chat's wizard on, if it is walking this video, and say the
    next step under the reply."""
    cs = ChatState(core.settings)
    wz = cs.wizard(chat_id)
    if not wz or wz.get("ticker") != ticker or wz.get("workdate") != workdate:
        return reply
    if step == "done":
        cs.end_wizard(chat_id)
    else:
        cs.set_wizard(chat_id, ticker, workdate, step)
    reply.text = f"{reply.text}\n\n{WIZARD[step]}".strip()
    if step == "paste" and reply.keyboard is None:
        reply.keyboard = kb.ForceReply(input_field_placeholder="paste the script")
    return reply


# --------------------------------------------------------------------------
# The commands.
# --------------------------------------------------------------------------


async def _submit(core: BotCore, kind, text: str, ws) -> Reply:
    """Queue a render `render_request` approved, with Card/Cancel under it."""
    if kind is None or ws is None:
        return Reply(text)
    if core.queue is None:
        return Reply("⛔ the render queue is not running here — start the "
                     "bot with main.py.")
    try:
        await core.queue.submit(kind, ws.ticker, ws.workdate)
    except ValueError as e:
        return Reply(f"⛔ {e}")
    return Reply(text, keyboard=kb.queued_keyboard(ws.ticker, ws.workdate))


def _fmt_in(args: list[str]) -> str | None:
    return next((a.lower() for a in args[1:] if a.lower() in ("short", "long")),
                None)


# ---- the entry points
def c_help(c: Call):
    return Reply(help_text(c.args[0] if c.args else "", core=c.core,
                           chat_id=c.chat_id))


def c_card(c: Call):
    return c.core.video_card(c.args[0] if c.args else "", chat_id=c.chat_id)


def c_inbox(c: Call):
    return c.core.inbox_reply()


def c_go(c: Call):
    if not c.args:
        return Reply("Usage: /go TICKER — one SHORT from the workbook to "
                     "YouTube, asking for one thing at a time.")
    reply = c.core.start_lane(c.chat_id, "short", c.args[0])
    ws = c.core.context.get(c.chat_id)
    if ws is None or not reply.text.startswith("📁"):
        return reply
    ChatState(c.core.settings).set_wizard(c.chat_id, ws.ticker, ws.workdate,
                                          "workbook")
    reply.text += "\n\n" + WIZARD["workbook"]
    return reply


# ---- /new
def c_new_short(c: Call):
    return c.core.start_lane(c.chat_id, "short", c.args[0] if c.args else "")


def c_new_long(c: Call):
    return c.core.start_lane(c.chat_id, "long", c.args[0] if c.args else "")


def c_new_update(c: Call):
    return c.core.start_lane(c.chat_id, "long", c.args[0] if c.args else "",
                             update=True)


def c_new_headline(c: Call):
    return c.core.headline_command(c.chat_id, c.args)


# ---- /script
def c_script(c: Call):
    return c.core.script_listing(c.chat_id)


def c_edit(c: Call):
    return c.core.edit_script(c.chat_id, c.args, raw_args=c.raw)


def c_replace(c: Call):
    return c.core.edit_script(c.chat_id, c.args, mode="replace", raw_args=c.raw)


def c_undo(c: Call):
    return c.core.undo_edit(c.chat_id)


def c_prompts(c: Call):
    return c.core.prompts_reply(c.chat_id)


def c_why(c: Call):
    return c.core.why_command(c.args)


def c_report(c: Call):
    return c.core.show_report(c.chat_id)


def c_swap(c: Call):
    ws = c.core.context.get(c.chat_id)
    if ws is None:
        return Reply("No active video — /new long TICKER first.")
    return c.core.swap_menu(ws.ticker, ws.workdate)


# ---- /render
async def c_render(c: Call):
    if not c.args:
        return Reply("Usage: /render [TICKER] [short|long]")
    kind, text, ws = await asyncio.to_thread(
        c.core.render_request, c.args[0], _fmt_in(c.args), False)
    return await _submit(c.core, kind, text, ws)


def _render_fmt(fmt: str):
    async def run(c: Call):
        if not c.args:
            return Reply(f"Usage: /render {fmt} [TICKER]")
        kind, text, ws = await asyncio.to_thread(
            c.core.render_request, c.args[0], fmt, False)
        return await _submit(c.core, kind, text, ws)
    run.__name__ = f"c_render_{fmt}"
    return run


async def c_draft(c: Call):
    if not c.args:
        return Reply("Usage: /render draft [TICKER]")
    kind, text, ws = await asyncio.to_thread(
        c.core.render_request, c.args[0], "long", True)
    return await _submit(c.core, kind, text, ws)


async def c_proof(c: Call):
    if not c.args:
        return Reply("Usage: /render proof [TICKER] [short|long]")
    kind, text, ws = await asyncio.to_thread(
        lambda: c.core.render_request(c.args[0], _fmt_in(c.args), draft=False,
                                      proof=True))
    return await _submit(c.core, kind, text, ws)


async def c_clips(c: Call):
    if not c.args:
        return Reply("Usage: /render clips [TICKER]")
    kind, text, ws = await asyncio.to_thread(c.core.repurpose_request,
                                             c.args[0])
    return await _submit(c.core, kind, text, ws)


# ---- /publish
def c_upload(c: Call):
    return c.core.upload_command(c.args)


def c_pair(c: Call):
    if not c.args:
        return Reply("Usage: /publish pair [TICKER] [YYYY-MM-DD HH:MM]")
    return c.core.upload_command([c.args[0], "pair", *c.args[1:]])


def c_probe(c: Call):
    return c.core.probe_command(c.args)


def c_scheduled(c: Call):
    return c.core.scheduled_text()


def c_calendar(c: Call):
    return c.core.calendar_text(c.args)


def c_correct(c: Call):
    return c.core.correct_command(c.args)


# ---- /jobs
def c_status(c: Call):
    if c.core.queue is None:
        from pipeline.jobs import JobStore
        from pipeline.models import JobStatus

        jobs = sorted(JobStore(c.core.settings).all(),
                      key=lambda j: j.updated_at, reverse=True)[:10]
        if not jobs:
            return Reply("No jobs yet.")
        return Reply("\n".join(f"• {j.ticker} {j.kind.value} — {j.status.value}"
                               + (f" ({j.detail})" if j.detail else "")
                               for j in jobs
                               if isinstance(j.status, JobStatus)))
    return Reply(c.core.queue.status_text())


def c_cancel(c: Call):
    if not c.args:
        return Reply("Usage: /jobs cancel [TICKER]")
    return c.core.cancel_jobs(c.args[0])


async def c_uncancel(c: Call):
    jobs, text = await asyncio.to_thread(c.core.undo_cancel_plan)
    requeued = 0
    for kind, ticker, workdate in jobs:
        if c.core.queue is None:
            break
        try:
            await c.core.queue.submit(kind, ticker, workdate)
            requeued += 1
        except ValueError:
            continue
    if jobs:
        text += f", {requeued} job(s) back in the queue."
    return Reply(text)


async def c_batch(c: Call):
    if c.args and c.args[0].lower() == "run":
        if c.core.queue is None:
            return Reply("⛔ the render queue is not running here.")
        _q, _s, text = await c.core.run_batch()
        return Reply(text)
    return await asyncio.to_thread(c.core.batch_text, c.args)


# ---- /ideas
def c_ideas(c: Call):
    return c.core.queue_text()


def c_idea(c: Call):
    return c.core.queue_add(c.args)


def c_unidea(c: Call):
    return c.core.queue_drop(c.args)


async def c_screen(c: Call):
    from pipeline.screener import screen_reply

    return await screen_reply(c.core, c.args[0].lower() if c.args else "all")


def c_watch(c: Call):
    return c.core.watch_command(c.args)


def c_earnings(c: Call):
    return c.core.earnings_command(c.args)


def c_thesis(c: Call):
    return c.core.thesis_text(c.args)


# ---- /stats
def c_retention(c: Call):
    return c.core.retention_text(c.args)


def c_lines(c: Call):
    return c.core.lines_text(c.args)


def c_shots(c: Call):
    return c.core.shots_text(c.args)


def c_stillness(c: Call):
    return c.core.stillness_text(c.args)


def c_hooks(c: Call):
    return c.core.hooks_text(c.args)


def c_rules(c: Call):
    return c.core.rules_text()


def c_runtime(c: Call):
    return c.core.runtime_text()


def c_lessons(c: Call):
    return c.core.lessons_text(c.args)


def c_experiments(c: Call):
    return c.core.experiments_reply()


def c_scoreboard(c: Call):
    return c.core.scoreboard_reply(c.args)


# ---- /search
def c_ask(c: Call):
    return c.core.ask_text(c.args)


def c_find(c: Call):
    return c.core.find_text(c.args)


def c_said(c: Call):
    return c.core.said_text(c.args)


# ---- /admin
def c_cost(c: Call):
    return c.core.cost_reply(c.args)


def c_kit(c: Call):
    from pipeline.gates import kit_doctor_text

    what = c.args[0].lower() if c.args else "doctor"
    if what not in ("doctor", "report"):
        return Reply("usage: /admin kit doctor")
    return Reply(kit_doctor_text(c.core.settings))


def c_quiet(c: Call):
    prefs = NotifyPrefs(c.core.settings)
    what = c.args[0].lower() if c.args else ""
    if what in ("on", "quiet", ""):
        if not what and prefs.level() == "quiet":
            prefs.set("verbose")
            return Reply("🔔 notifications: everything (progress included).")
        prefs.set("quiet")
        return Reply("🔕 notifications: only finished, failed and needs-you. "
                     "/admin quiet off for everything.")
    if what in ("off", "verbose", "loud"):
        prefs.set("verbose")
        return Reply("🔔 notifications: everything (progress included).")
    return Reply("usage: /admin quiet [on|off]")


def c_panel(c: Call):
    url = getattr(c.core, "panel_url", "")
    if not url:
        return Reply("The web panel is not running. PANEL_ENABLED=true in "
                     ".env and restart the bot.")
    return Reply(f"🖥 {url}\n\nThe link carries the panel's key — keep it in "
                 f"this chat. It answers only on {c.core.settings.panel_host}.")


# --------------------------------------------------------------------------
# The registry.
# --------------------------------------------------------------------------

FAMILIES: tuple[Family, ...] = (
    Family("go", "Guided SHORT",
           "a SHORT start to finish, one step at a time"),
    Family("card", "Video card",
           "where a video is, with the next step on a button"),
    Family("inbox", "Inbox", "everything waiting on you"),
    Family("new", "Starting a video", "start a video: short, long, update, "
           "headline"),
    Family("script", "Reviewing and editing the script",
           "read, edit, approve the script",
           notes=(
               "An edit that does not parse never lands. Every edit that does "
               "re-runs the gates, re-prices, and drops the approval — nothing "
               "renders from a version nobody read.")),
    Family("render", "Rendering",
           "render: final (money), draft, proof, clips",
           notes=(
               "**Every render writes to a temp file and `os.replace`s into "
               "position**, after its length has been checked, so a failed "
               "re-render cannot destroy the good final that was already "
               "there. **Segment boundaries are quantised to whole frames at "
               "plan time** with the remainder carried forward, so the "
               "picture no longer creeps ahead of the voice across a long "
               "cut.\n\n"
               "**The lane decides the format, and it is declared rather than "
               "inferred.** `/new short` or `/new long` sets it once; "
               "`current_format()` returns it. A script file that disagrees "
               "with the lane is reported, not followed.\n\n"
               "**A pasted script routes by the lane too**, never by whether "
               "it starts with a brace. A paste that looks cut off — a JSON "
               "body that never closes, or a message sitting exactly on "
               "Telegram's 4,096-character split point — is refused with "
               "\"send it as a .txt file\" rather than saved as half a "
               "script.")),
    Family("publish", "Publishing", "YouTube: upload, schedule, probe, "
           "calendar, correct"),
    Family("jobs", "The render queue", "the render queue: status, cancel, "
           "undo, overnight batch"),
    Family("ideas", "Finding the next one", "what to make next: backlog, "
           "screen, watch, thesis"),
    Family("stats", "Reading what the videos did",
           "what the videos did: retention, lines, hooks, scoreboard…",
           notes=(
               "Every command here is a read. None spends, none renders, none "
               "can fail a job. They exist because these measurements were "
               "already being taken and thrown away.")),
    Family("search", "Asking the bot about itself",
           "ask the bot's own records, or search them",
           notes=(
               "Both read what the bot has already saved: every script, "
               "filing brief, check report, thesis, idea, job, upload and "
               "journal line, and this README. Neither spends, renders, or "
               "changes anything.")),
    Family("admin", "Housekeeping", "spend, kit, notifications, the panel"),
    Family("help", "Help", "this list; /help FAMILY for details"),
)

COMMANDS: tuple[Command, ...] = (
    # entry points
    Command("go", "", "TICKER", "a SHORT start to finish, one step at a time",
            c_go, example="{T}", doc=(
                "Walks one SHORT from the workbook to YouTube, asking for "
                "exactly the next thing: the workbook, the paste, the "
                "approval, the render (asked twice — it spends), the upload. "
                "Every step is an ordinary step: leave the wizard at any "
                "point and carry on by hand.")),
    Command("card", "", "[TICKER]",
            "where a video is, with the next step on a button", c_card,
            ticker="optional", example="{T}", doc=(
                "One message per video — data, angle, script, gates, "
                "approval with its price, renders, the job in flight, the "
                "upload — and the next step on a button. **It edits itself "
                "as the video moves**: a render's progress updates the card "
                "rather than adding messages. No ticker: the video you are "
                "working on.")),
    Command("inbox", "", "", "everything waiting on you", c_inbox, doc=(
        "Scripts waiting for approval, blocked reports, approved scripts not "
        "rendered, finals not uploaded, publishes in the next 48 hours, "
        "retention ready to read, and anything that failed overnight — one "
        "button each. Also sent every morning at `INBOX_HOUR`.")),
    # /new
    Command("new", "short", "TICKER", "start a SHORT (9:16, 45–55s)",
            c_new_short, aliases=("short",), example="{T}", doc=(
                "Opens a SHORT (9:16, 45–55s), pulls a live quote for the "
                "move context, and asks for the refreshed workbook. "
                "`prompt_short.md` follows the upload.")),
    Command("new", "long", "TICKER", "start a LONG (16:9 deep dive)",
            c_new_long, aliases=("long",), example="{T}", doc=(
                "Opens a LONG (16:9 deep dive) **and starts reading the "
                "filings immediately** — the latest 10-K, the prior year's "
                "and the quarterly pair, in parallel with you refreshing the "
                "workbook. Two steps: Step 1 returns ranked angles (pick one "
                "with its button, or reply with a tweak), Step 2 is the "
                "writing prompt.")),
    Command("new", "update", "TICKER",
            "revisit a covered name: what I said, what happened, was I right",
            c_new_update, aliases=("update",), example="{T}", doc=(
                "Revisits a name already covered — what I said, what "
                "happened, was I right, what now. One step, no angle to "
                "pick. Gets the same filing brief, additionally **graded "
                "against what the last video claimed**. Refuses (and points "
                "at `/new long`) when no thesis is on file.")),
    Command("new", "headline", "TICKER <text or URL>",
            "a SHORT about one specific headline", c_new_headline,
            aliases=("headline",), example="{T} beats on margins", doc=(
                "A SHORT about one specific headline. `/new headline macro "
                "<text>` for an index/macro take. Mode is detected (company "
                "/ earnings / macro) and can be forced with a leading `a:`, "
                "`b:` or `c:`. The mode sets the lane and picks the shot "
                "template."),
            ack="⏳ reading the headline…"),
    # /script
    Command("script", "", "", "the stored script, numbered", c_script, doc=(
        "The stored script, numbered, so `/script edit N` and it agree.")),
    Command("script", "edit", "N <text>", "replace line N (N-M for a range; "
            "no text deletes it)", c_edit, aliases=("edit",),
            ack="⏳ editing and re-checking…", example="3 Revenue fell 12%.",
            doc="Replaces line N. `N-M` for a range; no text deletes the line."),
    Command("script", "replace", "old => new",
            "fix a figure or a phrase in place (all: for every hit)",
            c_replace, aliases=("replace",), ack="⏳ editing and re-checking…",
            example="12% => 14%", doc=(
                "Fixes a figure or a phrase by its own words. `all:` prefix "
                "replaces every occurrence.")),
    Command("script", "undo", "", "step back one revision", c_undo,
            aliases=("undo",), doc=(
                "Steps back one revision. A revert that fails validation "
                "costs nothing — the revision it took is put back.")),
    Command("script", "report", "", "the stored report, with Approve",
            c_report, doc=(
                "The validation and cost report on file, with its Approve / "
                "Swap / Edit buttons — without re-running the intake.")),
    Command("script", "swap", "", "the swap-clip menu (LONG)", c_swap, doc=(
        "One button per swappable visual in the LONG; each tap rotates that "
        "beat to its next take and re-prices the report.")),
    Command("script", "prompts", "", "re-send this lane's pre-filled prompt",
            c_prompts, aliases=("prompts",), doc=(
                "Re-sends the active video's pre-filled prompt.")),
    Command("script", "why", "[TICKER] [<your sentence>]",
            "why this one; prints above Approve, rides the description",
            c_why, aliases=("why",), ticker="text",
            example="nobody has read the 10-K", doc=(
                "Why this one is worth making, in your own words. Prints "
                "above Approve and rides the description. With no sentence "
                "it reads back what is recorded.")),
    # /render
    Command("render", "", "[TICKER] [short|long]",
            "render the approved script (this is where money is spent)",
            c_render, ticker="dated", spends=True, example="{T}", doc=(
                "Renders the approved script for the video's lane — the one "
                "step that spends. A format word picks one for a ticker that "
                "has both.")),
    Command("render", "long", "[TICKER]", "force the LONG",
            _render_fmt("long"), aliases=("render_long",), ticker="dated",
            spends=True, doc="Forces the LONG, for a ticker that has both."),
    Command("render", "short", "[TICKER]", "force the SHORT",
            _render_fmt("short"), aliases=("render_short",), ticker="dated",
            spends=True, doc="Forces the SHORT, for a ticker that has both."),
    Command("render", "proof", "[TICKER] [short|long]",
            "FULL-RES look test: real visuals, free voice, $0", c_proof,
            aliases=("proof",), ticker="dated", example="{T}", doc=(
                "Full-resolution look test: live visuals, free local voice, "
                "`$0`. The pass that answers \"what will this look like?\". "
                "Writes `short_proof.mp4` / `long_proof.mp4` — never over a "
                "paid final.")),
    Command("render", "draft", "[TICKER]",
            "cheap low-res LONG timing check (no voice spend)", c_draft,
            aliases=("draft",), ticker="dated", doc=(
                "LONG only, half resolution, free voice. Answers \"does the "
                "timing work?\".")),
    Command("render", "clips", "[TICKER]",
            "free 9:16 SHORTs cut from the finished LONG", c_clips,
            aliases=("repurpose",), ticker="dated", doc=(
                "Cuts the best two or three ~58s windows of a finished LONG "
                "into free vertical SHORTs.")),
    # /publish
    Command("publish", "", "[TICKER] [short|long|clip N] [again] "
            "[YYYY-MM-DD HH:MM]", "YouTube, private or scheduled (never "
            "public)", c_upload, aliases=("upload",), ticker="dated",
            example="{T} 2026-10-09 17:00", doc=(
                "YouTube upload — private, or scheduled at that time. Never "
                "public. A format reaches either lane, or a repurposed clip. "
                "A bare date means `PUBLISH_HOUR` in `PUBLISH_TIMEZONE`. The "
                "format's own thumbnail and `.srt` go up with the video, and "
                "the description is the render's package — the why, the "
                "transcript, and chapters cut to the rendered length. A "
                "render already uploaded is refused unless `again` says "
                "otherwise. A dropped upload resumes rather than starting a "
                "second one.")),
    Command("publish", "pair", "[TICKER] [YYYY-MM-DD HH:MM]",
            "two repurposed clips off one LONG, tagged as a pair", c_pair,
            ticker="dated", doc=(
                "Ships **two** repurposed clips off one long, tagged as a "
                "pair, so `/stats experiments` can compare them.")),
    Command("publish", "probe", "[TICKER] [short|long]",
            "one UNLISTED upload, to see where YouTube puts the AI label",
            c_probe, aliases=("probe",), ticker="dated", doc=(
                "One **unlisted** upload of a finished render with the "
                "synthetic-media box ticked, to see where YouTube puts the "
                "AI label on this channel's output. Never public, never "
                "scheduled, not recorded as a published video; delete it "
                "when you have looked.")),
    Command("publish", "scheduled", "", "what's queued to publish and when",
            c_scheduled, aliases=("scheduled",),
            doc="What is queued to publish, and when."),
    Command("publish", "calendar", "[weeks]",
            "the publishing week, with the gaps marked", c_calendar, doc=(
                "The next week (or N weeks) of scheduled publishes, day by "
                "day in `PUBLISH_TIMEZONE`, with the empty days marked — "
                "something for `/jobs batch` to plan against.")),
    Command("publish", "correct", "[TICKER <what was wrong>]",
            "pin a correction on a shipped video", c_correct,
            aliases=("correct",), ticker="optional", doc=(
                "Pins a correction on a video that has already shipped, "
                "amends its description and records it. No arguments lists "
                "every correction ever issued.")),
    # /jobs
    Command("jobs", "", "", "the render queue", c_status,
            aliases=("status",), doc=(
                "The job queue, with the by-product links the delivery "
                "produced — thumbnail, `.srt`, upload package, credits. Jobs "
                "left QUEUED by a restart are picked back up.")),
    Command("jobs", "cancel", "[TICKER]",
            "cancel queued/running jobs + pending approval", c_cancel,
            aliases=("cancel",), ticker="dated", doc=(
                "Cancels queued and running jobs plus any pending approval. "
                "**Undo within a minute** puts the approvals back and "
                "re-queues the jobs.")),
    Command("jobs", "undo", "", "undo the last cancel (within a minute)",
            c_uncancel, doc=(
                "Restores the approvals the last cancel withdrew and "
                "re-queues its jobs, within a minute of it. An approval pins "
                "the script's hash, so a script edited since stays "
                "unapproved.")),
    Command("jobs", "batch", "[TICKER [fmt] | run | clear | list]",
            "queue renders to run unattended overnight", c_batch,
            aliases=("batch",), doc=(
                "Queues renders to run unattended overnight. Harmless when "
                "the machine is off — nothing expires.")),
    # /ideas
    Command("ideas", "", "", "the ranked backlog", c_ideas, doc=(
        "The ranked backlog, fed by every screen and by any thesis that "
        "moves.")),
    Command("ideas", "add", "TICKER <why>", "add one by hand", c_idea,
            aliases=("idea",), doc="Adds one by hand."),
    Command("ideas", "drop", "TICKER", "drop one", c_unidea,
            aliases=("unidea",), doc="Drops one."),
    Command("ideas", "screen", "[trending|value|all]",
            "ranked candidates (trending → SHORT, value → LONG)", c_screen,
            aliases=("screen",), doc=(
                "Ranked candidates. Trending → SHORT, value → LONG, plus the "
                "update lane (covered names whose thesis has moved). Each "
                "candidate is a button that opens it in its lane.")),
    Command("ideas", "watch", "[TICKER | drop TICKER | list]",
            "intraday watch (published names join automatically)", c_watch,
            aliases=("watch",), doc=(
                "Intraday watch, in `SCREEN_TIMEZONE` rather than the "
                "machine clock. Published names join automatically.")),
    Command("ideas", "earnings", "TICKER YYYY-MM-DD [bmo|amc]",
            "so the bot flags the print both sides", c_earnings,
            aliases=("earnings",),
            doc="Records a print date so the bot flags it both sides."),
    Command("ideas", "thesis", "[TICKER]",
            "what we said, and whether the numbers still back it", c_thesis,
            aliases=("thesis",), ticker="optional", doc=(
                "What we said about a name, re-checked against today's "
                "numbers. No ticker lists every thesis on file with its "
                "status.")),
    # /stats
    Command("stats", "retention", "[TICKER]",
            "per-chapter drop-off; no ticker = the evidence across all",
            c_retention, aliases=("retention",), ticker="optional", doc=(
                "Per-chapter drop-off. No ticker aggregates the evidence "
                "across everything published.")),
    Command("stats", "lines", "[TICKER]",
            "where a published video lost them, to the sentence", c_lines,
            aliases=("lines",), ticker="plain", doc=(
                "Where a published video lost them, **to the sentence** — "
                "retention joined against the word timings the render "
                "stored.")),
    Command("stats", "shots", "[TICKER]",
            "which shots of a published video lose people", c_shots,
            aliases=("shots",), ticker="plain", doc=(
                "Which shots of a published video lose people, and how long "
                "each of them runs.")),
    Command("stats", "stillness", "[TICKER]",
            "every stretch where the picture holds still too long",
            c_stillness, aliases=("stillness",), ticker="dated", doc=(
                "Every stretch where the audio runs and the picture holds "
                "still for more than eight seconds. Read off the manifest, so "
                "it works offline and on a video that has never shipped.")),
    Command("stats", "hooks", "[short|long]",
            "openers ranked by what they held", c_hooks, aliases=("hooks",),
            doc=("Openers ranked by what they held over their own first five "
                 "seconds, rather than by the whole video's average.")),
    Command("stats", "rules", "", "what the voice rules are worth, measured",
            c_rules, aliases=("rules",), doc=(
                "Mean hold on sentences carrying a turn, a question, a spoken "
                "figure, first person — against those without.")),
    Command("stats", "runtime", "", "hold against how long the videos run",
            c_runtime, aliases=("runtime",),
            doc="Hold against how long the videos run, per band."),
    Command("stats", "lessons", "[now]",
            "what the writer is told about where viewers left", c_lessons,
            aliases=("lessons",), doc=(
                "The note every writing prompt carries about where viewers "
                "left, per lane, rewritten weekly. `now` rewrites it "
                "immediately. Free: the model call never reaches a paid "
                "tier.")),
    Command("stats", "experiments", "", "clip pairs, and which one held",
            c_experiments, aliases=("experiments",), doc=(
                "Clip pairs cut from one long and shipped as a pair, and "
                "which one held.")),
    Command("stats", "scoreboard", "[YYYY-Qn]",
            "what we said and what happened, for a quarter", c_scoreboard,
            aliases=("scoreboard",), doc=(
                "What we said and what happened, for a quarter. It leads "
                "with the calls that were wrong, deliberately.")),
    # /search
    Command("search", "", "<question>",
            "the local AI answers from everything the bot has saved", c_ask,
            aliases=("ask",), ack="🔎 reading the records…",
            example="what did voice cost in September", doc=(
                "The local model answers from the bot's own records, citing "
                "what it read, or says it has nothing on file. Counts and "
                "totals are worked out by code and never reach the model.")),
    Command("search", "find", "<words>",
            "search everything the bot has saved, no AI", c_find,
            aliases=("find",), doc=(
                "Every saved record with those words, ranked, no AI "
                "involved. Works with Ollama off.")),
    Command("search", "said", "<phrase>",
            "every earlier use of a line, across every script shipped",
            c_said, aliases=("said",), doc=(
                "Every earlier use of a line, across every script ever "
                "shipped.")),
    # /admin
    Command("admin", "cost", "[explain|reconciled]",
            "month-to-date spend vs cap", c_cost, aliases=("cost",), doc=(
                "Month-to-date spend against the cap, and how long ago "
                "anyone checked it against the provider. `explain`: where "
                "the month went, per video and tier. `reconciled`: stamp "
                "today after comparing against the provider's dashboard.")),
    Command("admin", "kit", "doctor",
            "unresolved tag keys, never-used artwork, unregistered PNGs",
            c_kit, aliases=("kit",), doc=(
                "Unresolved tag keys, artwork nothing has ever used, PNGs "
                "with no registry entry.")),
    Command("admin", "quiet", "[on|off]",
            "only finished, failed and needs-you notifications", c_quiet,
            doc=("Keeps only finished, failed and needs-you pushes (no "
                 "\"started\", no progress). On its own it toggles.")),
    Command("admin", "panel", "", "the web panel's link", c_panel, doc=(
        "The link to the web control panel, when it is running.")),
    # /help
    Command("help", "", "[FAMILY]", "this list; /help FAMILY for details",
            c_help, aliases=("start",), example="render",
            doc="The command list, in chat. `/help render` for one family."),
)

FAMILY_BY_NAME = {f.name: f for f in FAMILIES}
SUBS: dict[str, dict[str, Command]] = {}
for _c in COMMANDS:
    SUBS.setdefault(_c.family, {})[_c.sub] = _c
ALIASES: dict[str, Command] = {a: c for c in COMMANDS for a in c.aliases}
# A family that can be named as a sub-word too (`/admin cost` and the old
# `/cost`): a sub word must not shadow a family's default in another one.
assert not set(ALIASES) & set(FAMILY_BY_NAME), "an alias shadows a family"


def telegram_names() -> list[str]:
    """Every name a CommandHandler is registered for."""
    return [f.name for f in FAMILIES] + sorted(ALIASES)


def menu_commands() -> list[tuple[str, str]]:
    """The trimmed Telegram "/" menu: the entry points and the families."""
    return [(f.name, f.blurb[:250]) for f in FAMILIES]


# --------------------------------------------------------------------------
# Dispatch.
# --------------------------------------------------------------------------


def _drop_first_word(raw: str) -> str:
    parts = (raw or "").lstrip().split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def resolve(name: str, args: list[str], raw: str = ""
            ) -> tuple[Command | None, Family | None, list[str], str]:
    """`(command, family, args, raw)` for `/name args…`. The command is None
    when the family has no default (its help is the answer) or the name is
    unknown (the family is None too)."""
    name = (name or "").lower().lstrip("/").split("@")[0]
    if name in ALIASES:
        cmd = ALIASES[name]
        return cmd, FAMILY_BY_NAME[cmd.family], list(args), raw
    fam = FAMILY_BY_NAME.get(name)
    if fam is None:
        return None, None, list(args), raw
    subs = SUBS.get(name, {})
    if args and args[0].lower() in subs and args[0].lower():
        return (subs[args[0].lower()], fam, list(args[1:]),
                _drop_first_word(raw))
    return subs.get(""), fam, list(args), raw


def _fill_ticker(c: Call, cmd: Command) -> str | None:
    """Put the active video in front of the args when the ticker is
    missing. Returns a refusal when there is nothing to put there."""
    mode = cmd.ticker
    if mode in ("", "optional"):
        return None
    first = c.args[0] if c.args else ""
    if mode == "text":
        if first and _has_workspace(c.core, first):
            return None
    elif first and looks_like_ticker(first):
        return None
    ws = c.core.context.get(c.chat_id)
    if ws is None:
        return (f"Which video? This chat has no active one — "
                f"{cmd.slash} TICKER, or start one with /new.")
    token = ws.ticker if mode == "plain" else f"{ws.ticker}@{ws.workdate}"
    c.args = [token] + c.args
    c.filled = f"{ws.ticker} {ws.workdate}"
    return None


async def run_command(core: BotCore, chat_id: int, name: str,
                      args: list[str], raw: str = "",
                      say: Say | None = None) -> Reply:
    """Resolve and run one command; the Telegram glue and the panel both
    come through here."""
    cmd, fam, args, raw = resolve(name, args, raw)
    if fam is None:
        return Reply(unknown_command_text(name))
    if cmd is None:
        return Reply(family_help(fam.name, core=core, chat_id=chat_id))
    c = Call(core, chat_id, args, raw, say)
    refusal = _fill_ticker(c, cmd)
    if refusal:
        return Reply(refusal)
    if cmd.ack and say is not None and c.args:     # not before a usage line
        await say(Reply(cmd.ack))
    if inspect.iscoroutinefunction(cmd.run):
        result = await cmd.run(c)
    else:
        result = await asyncio.to_thread(cmd.run, c)
    reply = _reply(result)
    if c.filled and not reply.text.startswith("📁"):
        reply.text = f"📁 {c.filled}\n{reply.text}"
    return reply


def unknown_command_text(name: str) -> str:
    """"Did you mean…" against every name the bot answers."""
    name = (name or "").lower().lstrip("/").split("@")[0]
    names = telegram_names()
    subs = [c.name for c in COMMANDS if c.sub]
    close = difflib.get_close_matches(name, names + [s.replace(" ", "")
                                                     for s in subs],
                                      n=3, cutoff=0.6)
    # A sub-word typed as a command (`/proof`, `/calendar`) is a family's.
    by_sub = [c.slash for c in COMMANDS if c.sub == name]
    hints = by_sub + [f"/{n}" if n in names else
                      next((c.slash for c in COMMANDS
                            if c.name.replace(" ", "") == n), f"/{n}")
                      for n in close]
    seen: list[str] = []
    for h in hints:
        if h not in seen:
            seen.append(h)
    if seen:
        return f"Unknown command /{name}. Did you mean {' or '.join(seen[:3])}?"
    return f"Unknown command /{name}. /help lists them."


# --------------------------------------------------------------------------
# Help, generated.
# --------------------------------------------------------------------------

FLOW = (
    "Flow: /go TICKER walks a SHORT end to end. By hand: /new short|long "
    "TICKER → refresh the template and upload it as dennis_data.xlsx → run "
    "the prompt in Claude → (LONG: tap an angle; I auto-pull the 10-K shots) "
    "→ paste the output back here → read the report → tweak it (/script edit, "
    "/script replace — every revision re-runs the gates and re-prices) → "
    "Approve ✅ → Render 💰. Nothing paid happens before Approve, and the "
    "approval is pinned to the exact version you approved.")


def _family_line(fam: Family) -> str:
    subs = [c.sub for c in COMMANDS if c.family == fam.name and c.sub]
    default = SUBS.get(fam.name, {}).get("")
    usage = default.usage if default and not subs else ""
    if subs:
        words = "|".join(subs)
        return (f"/{fam.name} [{words}] — {fam.blurb}" if default
                else f"/{fam.name} {words} — {fam.blurb}")
    return f"/{fam.name} {usage}".rstrip() + f" — {fam.blurb}"


def help_text(family: str = "", core: BotCore | None = None,
              chat_id: int | None = None) -> str:
    if family:
        return family_help(family, core=core, chat_id=chat_id)
    lines = ["Dennis — commands. The ticker is optional wherever it is in "
             "[brackets]: it defaults to the video you are working on.", ""]
    for fam in FAMILIES:
        lines.append(_family_line(fam))
        if fam.name == "inbox":
            lines.append("")
    old = ", ".join(f"/{a}" for a in sorted(ALIASES) if a != "start")
    lines += ["", f"Old names still work: {old}.", "", FLOW]
    return "\n".join(lines)


def family_help(name: str, core: BotCore | None = None,
                chat_id: int | None = None) -> str:
    name = name.lower().lstrip("/")
    if name not in FAMILY_BY_NAME and name in ALIASES:
        name = ALIASES[name].family
    fam = FAMILY_BY_NAME.get(name)
    if fam is None:
        return unknown_command_text(name)
    ticker = "TICKER"
    if core is not None and chat_id is not None:
        ws = core.context.get(chat_id)
        if ws is not None:
            ticker = ws.ticker
    lines = [f"/{fam.name} — {fam.title}", ""]
    for c in COMMANDS:
        if c.family != fam.name:
            continue
        lines.append(f"{c.line} — {c.help}"
                     + (" 💰" if c.spends else ""))
        if c.example:
            lines.append(f"   e.g. {c.slash} {c.example.format(T=ticker)}")
        if c.aliases:
            lines.append(f"   (was {', '.join('/' + a for a in c.aliases)})")
    return "\n".join(lines)


def _md(text: str) -> str:
    return text.replace("|", "\\|")


def readme_markdown() -> str:
    """The README's command reference, generated. `tests/test_docs.py`
    compares it with the README's copy."""
    out: list[str] = []
    for fam in FAMILIES:
        out.append(f"### /{fam.name} — {fam.title}")
        out.append("")
        out.append("| command | what it does |")
        out.append("|---|---|")
        for c in COMMANDS:
            if c.family != fam.name:
                continue
            cell = f"`{_md(c.line)}`"
            doc = c.doc or c.help
            if c.spends:
                doc += " **Spends.**"
            out.append(f"| {cell} | {_md(doc)} |")
        if fam.notes:
            out += ["", fam.notes]
        out.append("")
    out.append("### Old command names")
    out.append("")
    out.append("Every name the bot answered before the families still works, "
               "as a hidden alias of the command it became.")
    out.append("")
    out.append("| old | now |")
    out.append("|---|---|")
    for alias in sorted(ALIASES):
        out.append(f"| `/{alias}` | `{ALIASES[alias].slash}` |")
    return "\n".join(out).rstrip() + "\n"


def registry_json(core: BotCore | None = None,
                  chat_id: int | None = None) -> dict:
    """The registry for the web panel: families, commands, and the active
    video it should prefill."""
    active = None
    if core is not None and chat_id is not None:
        ws = core.context.get(chat_id)
        if ws is not None:
            active = {"ticker": ws.ticker, "workdate": ws.workdate}
    return {
        "active": active,
        "families": [{"name": f.name, "title": f.title, "blurb": f.blurb}
                     for f in FAMILIES],
        "commands": [{"family": c.family, "sub": c.sub, "name": c.name,
                      "usage": c.usage, "help": c.help, "doc": c.doc or c.help,
                      "ticker": c.ticker, "spends": c.spends,
                      "aliases": list(c.aliases),
                      "example": c.example}
                     for c in COMMANDS],
    }


# --------------------------------------------------------------------------
# Things that are not commands: text, files, buttons.
# --------------------------------------------------------------------------


async def handle_text(core: BotCore, chat_id: int, text: str,
                      say: Say | None = None) -> Reply:
    """A plain message: the answer to a question a button asked, an angle
    pick, or a script."""
    cs = ChatState(core.settings)
    pending = cs.pending(chat_id)
    if pending and not core.looks_like_script(text):
        cs.answered(chat_id)
        words = text.split()
        if text.strip().lower().rstrip(".!") in ("cancel", "no", "stop",
                                                  "never mind", "nevermind"):
            return Reply("OK — left as it was.")
        if pending["kind"] == "schedule":
            target = f"{pending['ticker']}@{pending['workdate']}"
            reply = await asyncio.to_thread(
                core.upload_command, [target, pending["fmt"], *words])
            if reply.text.startswith("📺"):
                reply = _wizard_step(core, chat_id, pending["ticker"],
                                     pending["workdate"], "done", reply)
            return reply
        if pending["kind"] == "correct":
            return _reply(await asyncio.to_thread(
                core.correct_command, [pending["ticker"], *words]))
    slow = core.looks_like_script(text)
    if slow and say is not None:
        await say(Reply("⏳ got it — planning the visuals, this takes a "
                        "minute."))
    reply = await asyncio.to_thread(core.intake_script, chat_id, text)
    ws = core.context.get(chat_id)
    if ws is not None and isinstance(reply.keyboard, kb.InlineKeyboardMarkup) \
            and any(b.callback_data.startswith("a|")
                    for row in reply.keyboard.inline_keyboard for b in row):
        reply = _wizard_step(core, chat_id, ws.ticker, ws.workdate,
                             "approve", reply)
    return reply


async def handle_upload(core: BotCore, chat_id: int, filename: str,
                        data: bytes, say: Say | None = None) -> Reply:
    if say is not None:
        await say(Reply("⏳ got the file — reading it now."))
    reply = await asyncio.to_thread(core.handle_upload, chat_id, filename, data)
    ws = core.context.get(chat_id)
    if ws is not None and reply.text.startswith("💾 saved"):
        reply = _wizard_step(core, chat_id, ws.ticker, ws.workdate, "paste",
                             reply)
    return reply


async def handle_callback(core: BotCore, chat_id: int, data: str,
                          say: Say | None = None) -> Reply:
    """Every button, for Telegram and the panel alike."""
    from bot.keyboards import CODE_LANES

    async def tell(text: str) -> None:
        if say is not None:
            await say(Reply(text))

    parts = (data or "").split("|")
    op = parts[0]
    n = len(parts)
    if op == "a" and n == 5:
        # Approve re-runs the gate battery now, which reads the workbook and
        # the screengrabs off disk — seconds, not milliseconds (F2).
        await tell("⏳ re-checking before approval…")
        reply = await asyncio.to_thread(core.approve, *parts[1:5])
        if reply.text.startswith("✅"):
            reply = _wizard_step(core, chat_id, parts[2], parts[3], "render",
                                 reply)
        return reply
    if op == "x" and n == 4:
        return await asyncio.to_thread(core.cancel_approval, *parts[1:4])
    if op == "w" and n == 3:
        return await asyncio.to_thread(core.swap_menu, parts[1], parts[2])
    if op == "w!" and n == 3:
        # Both of these re-run the full intake — the plan, the gates, the
        # contact sheet — so they go off the loop like a paste does (F2).
        core.context.set(chat_id, parts[1], parts[2])
        raw_file = Workspace(core.settings, parts[1], parts[2]).path \
            / "script_long.raw.txt"
        if not raw_file.exists():
            return Reply("No LONG script on file.")
        await tell("⏳ rebuilding the report…")
        return await asyncio.to_thread(
            core.intake_script, chat_id, raw_file.read_text(encoding="utf-8"),
            from_file=True)
    if op == "s" and n == 4:
        await tell("⏳ swapping the clip…")
        return await asyncio.to_thread(core.swap_key, chat_id, *parts[1:4])
    if op == "fv" and n == 4:
        return await asyncio.to_thread(core.veto_filing, chat_id, *parts[1:4])
    if op == "n" and n == 3:
        # A screener candidate carries its own lane (G3).
        lane = CODE_LANES.get(parts[1])
        if not lane:
            return Reply("Unknown lane on that button.")
        return await asyncio.to_thread(core.start_lane, chat_id, lane, parts[2])
    if op == "e" and n == 3:
        core.context.set(chat_id, parts[1], parts[2])
        return await asyncio.to_thread(core.script_listing, chat_id)
    if op == "k" and n == 3:
        return await asyncio.to_thread(core.show_report, chat_id, parts[1],
                                       parts[2])
    if op == "g" and n == 4:
        await tell(f"⏳ locking angle {parts[3]} and pulling the filing "
                   f"shots…")
        return await asyncio.to_thread(core.angle_pick, chat_id, *parts[1:4])
    if op == "p" and n == 3:
        core.context.set(chat_id, parts[1], parts[2])
        return await asyncio.to_thread(core.prompts_reply, chat_id)
    if op == "q" and n == 5:
        what, t, d, code = parts[1:5]
        fmt = kb.CODE_FMTS.get(code, "short")
        target = f"{t}@{d}"
        if what == "c":
            kind, text, ws = await asyncio.to_thread(core.repurpose_request,
                                                     target)
        else:
            kind, text, ws = await asyncio.to_thread(
                lambda: core.render_request(target, fmt, draft=what == "d",
                                            proof=what == "p"))
        return await _submit(core, kind, text, ws)
    if op == "r" and n == 4:
        fmt = kb.CODE_FMTS.get(parts[1], "short")
        return await asyncio.to_thread(core.render_confirm, fmt, parts[2],
                                       parts[3])
    if op == "r!" and n == 4:
        fmt = kb.CODE_FMTS.get(parts[1], "short")
        kind, text, ws = await asyncio.to_thread(
            core.render_request, f"{parts[2]}@{parts[3]}", fmt, False)
        reply = await _submit(core, kind, text, ws)
        if ws is not None and not reply.text.startswith("⛔"):
            reply = _wizard_step(core, chat_id, parts[2], parts[3],
                                 "rendering", reply)
        return reply
    if op == "u" and n == 4:
        fmt = kb.CODE_FMTS.get(parts[1], "short")
        await tell("⏳ uploading — private, never public…")
        reply = await asyncio.to_thread(
            core.upload_command, [f"{parts[2]}@{parts[3]}", fmt])
        if reply.text.startswith("📺"):
            reply = _wizard_step(core, chat_id, parts[2], parts[3], "done",
                                 reply)
        return reply
    if op == "us" and n == 4:
        fmt = kb.CODE_FMTS.get(parts[1], "short")
        ChatState(core.settings).ask(chat_id, "schedule", fmt=fmt,
                                     ticker=parts[2], workdate=parts[3])
        return Reply(
            f"📅 When should {parts[2]} {fmt.upper()} go public? Reply with "
            f"YYYY-MM-DD HH:MM ({core.settings.publish_timezone}), or just a "
            f"date for {core.settings.publish_hour}:00.",
            keyboard=kb.ForceReply(input_field_placeholder="2026-10-09 17:00"))
    if op == "rt" and n == 2:
        return await asyncio.to_thread(core.retention_text, [parts[1]])
    if op == "cr" and n == 2:
        ChatState(core.settings).ask(chat_id, "correct", ticker=parts[1])
        return Reply(
            f"✍️ What was wrong in {parts[1]}'s video? Reply with the "
            f"correction as it should read.",
            keyboard=kb.ForceReply(input_field_placeholder="the right number"))
    if op == "c" and n == 3:
        return await asyncio.to_thread(core.video_card, parts[1],
                                       workdate=parts[2])
    if op == "j" and n == 3:
        return await asyncio.to_thread(core.cancel_jobs,
                                       f"{parts[1]}@{parts[2]}")
    if op == "z":
        return await c_uncancel(Call(core, chat_id, []))
    if op == "ib":
        return await asyncio.to_thread(core.inbox_reply)
    return Reply("Unknown action — that button is from an older version.")


# --------------------------------------------------------------------------
# The cards that edit themselves, and the follow-up a finished job sends.
# --------------------------------------------------------------------------

FINAL_KINDS = {"render_short": "short", "render_long": "long"}
TRIAL_KINDS = {"render_proof_short": "short", "render_proof_long": "long",
               "render_draft_long": "long"}


class CardBoard:
    """Remembers which messages are video cards and edits them in place as
    their video moves; sends the next-step buttons when a job finishes.

    `send(chat_id, reply) -> message_id` and `edit(chat_id, message_id,
    reply)` are the frontend's (Telegram's) coroutines. `job_changed` is
    called from whichever thread saved the job, so it hops to the loop.
    """

    PROGRESS_EVERY_S = 10.0
    KEEP_PER_VIDEO = 3

    def __init__(self, core: BotCore, send=None, edit=None):
        self.core = core
        self.send = send
        self.edit = edit
        self.loop: asyncio.AbstractEventLoop | None = None
        self.path = Path(core.settings.state_dir) / "cards.json"
        self._status: dict[str, str] = {}
        self._last_edit: dict[str, float] = {}

    # ---- which messages are cards
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def remember(self, key: str, chat_id: int, message_id: int) -> None:
        data = self._load()
        rows = [r for r in data.get(key, []) if r[0] != chat_id]
        rows.append([chat_id, message_id])
        data[key] = rows[-self.KEEP_PER_VIDEO:]
        if len(data) > 200:                # old videos stop being edited
            for old in sorted(data)[:len(data) - 200]:
                data.pop(old, None)
        _write(self.path, json.dumps(data))

    def cards(self, key: str) -> list[tuple[int, int]]:
        return [(int(c), int(m)) for c, m in self._load().get(key, [])]

    # ---- refreshing
    async def refresh(self, key: str) -> int:
        if self.edit is None:
            return 0
        targets = self.cards(key)
        if not targets:
            return 0
        ticker, _, workdate = key.partition("@")
        reply = await asyncio.to_thread(self.core.video_card, ticker,
                                        workdate=workdate)
        done = 0
        for chat_id, message_id in targets:
            try:
                await self.edit(chat_id, message_id, reply)
                done += 1
            except Exception as e:  # noqa: BLE001 - "not modified", deleted
                log.debug("card %s in %s not edited: %s", key, chat_id, e)
        self._last_edit[key] = time.monotonic()
        return done

    def job_changed(self, job) -> None:
        """JobStore listener: from any thread."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._on_job, job)
        except RuntimeError:
            pass

    def _on_job(self, job) -> None:
        key = f"{job.ticker}@{job.workdate}"
        status = job.status.value
        before = self._status.get(job.id)
        self._status[job.id] = status
        moved = before != status
        recent = (time.monotonic() - self._last_edit.get(key, 0.0)
                  < self.PROGRESS_EVERY_S)
        if moved or not recent:
            asyncio.ensure_future(self.refresh(key))
        if moved and status == "done":
            asyncio.ensure_future(self.finished(job))

    async def finished(self, job) -> None:
        """The next step, on buttons, when a render lands."""
        if self.send is None:
            return
        kind = job.kind.value
        t, d = job.ticker, job.workdate
        if kind in FINAL_KINDS:
            fmt = FINAL_KINDS[kind]
            base = Reply(f"✅ {t} {fmt.upper()} final is ready — what next?",
                         keyboard=kb.delivered_keyboard(fmt, t, d))
        elif kind in TRIAL_KINDS:
            fmt = TRIAL_KINDS[kind]
            label = "draft" if "draft" in kind else "proof"
            base = Reply(f"✅ {t} {fmt.upper()} {label} is ready — look it "
                         f"over, then:",
                         keyboard=kb.delivered_keyboard(fmt, t, d, final=False))
        else:
            return
        wizards = ChatState(self.core.settings).wizards()
        for chat_id in self.core.settings.operator_chat_ids:
            reply = Reply(base.text, keyboard=base.keyboard)
            wz = wizards.get(chat_id)
            if (kind in FINAL_KINDS and wz and wz.get("ticker") == t
                    and wz.get("workdate") == d):
                reply = _wizard_step(self.core, chat_id, t, d, "upload", reply)
            try:
                await self.send(chat_id, reply)
            except Exception:  # noqa: BLE001 - the next chat still hears
                log.exception("could not send the next step to %s", chat_id)


# --------------------------------------------------------------------------
# The morning inbox.
# --------------------------------------------------------------------------


def schedule_inbox(application, core: BotCore, send=None) -> None:
    """Send `/inbox` every morning at INBOX_HOUR (machine clock), when there
    is something in it. Checked every quarter-hour so a box that wakes late
    still sends today's, once."""
    settings = core.settings
    if not getattr(settings, "inbox_enabled", True):
        log.info("morning inbox disabled (INBOX_ENABLED)")
        return
    sent: set[str] = set()

    async def inbox_job(ctx) -> None:
        from datetime import datetime as _dt

        now = _dt.now()
        today = now.date().isoformat()
        if now.hour < settings.inbox_hour or today in sent:
            return
        sent.add(today)
        reply = await asyncio.to_thread(core.inbox_reply)
        if reply.text.startswith("📥 Inbox zero"):
            return
        for chat_id in settings.operator_chat_ids:
            try:
                if send is not None:
                    await send(chat_id, reply)
                else:
                    await ctx.bot.send_message(chat_id, reply.text,
                                               reply_markup=reply.keyboard)
            except Exception:  # noqa: BLE001
                log.exception("could not send the inbox to %s", chat_id)

    application.job_queue.run_repeating(
        inbox_job, interval=15 * 60, first=90, name="morning_inbox")
    log.info("morning inbox at %02d:00 (machine clock)", settings.inbox_hour)


if __name__ == "__main__":  # pragma: no cover - `python -m bot.commands`
    import sys

    if "--readme" in sys.argv:
        print(readme_markdown(), end="")
    else:
        print(help_text())
