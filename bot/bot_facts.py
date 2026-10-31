"""What `/ask` is told about the bot as it is right now (10-23).

He asked for the local model to know "the ins and outs of the bot ... what's
in there", read-only, and did not trust it to go looking by itself. So the
bot does the looking: each `Drawer` here is one part of the bot's state as
plain text (the open videos, the queue and spend, the library, the
switches and settings, the health checks, the ideas and the calendar, and a
manual of the page), and `pipeline.recall.ask` opens the ones a question's
words reach and hands them to the model with the saved records.

Every drawer reads the same view the page draws (`bot.panel_pages`,
`bot.panel_views`, `pipeline.video_state`), so an answer and the screen can
never disagree. Nothing here writes, and no key, token or password is ever
put in a drawer: the settings drawer leaves out every field whose name says
it is one, then blanks any value that matches a secret.
"""

from __future__ import annotations

import re
from collections import Counter
from types import SimpleNamespace

from pipeline.recall import Drawer

# The page's screens, as the menu names them (pinned to index.html's tabs).
SCREENS: dict[str, str] = {
    "home": "Home: the big Next up button (the most urgent thing across all "
            "videos), the inbox, Start a video (ticker, lane, drop the "
            "workbook), the render queue with time left, this week's "
            "publishing and the month's spend. The Ask box opens a "
            "conversation in Chat.",
    "chat": "Chat: a conversation with the local AI about the bot, every "
            "conversation kept in a list (rename, delete, new). It shows "
            "what it is doing while it answers, writes the answer as it "
            "comes, lists the records it used, and reads a follow-up with "
            "the conversation. One question at a time; it waits while a "
            "render uses the graphics card and still answers there.",
    "videos": "Videos: every recent video as a card; a card opens its "
              "workspace, which walks through the steps below.",
    "ideas": "Ideas: the backlog as a table you add to and drop from, the "
             "last screener run, the watch list and earnings dates, with "
             "Start on every row.",
    "calendar": "Calendar: a month of published and scheduled videos with "
                "the empty days marked; click a free day to schedule a "
                "finished video into it.",
    "stats": "Stats: openers (hooks), the writing rules, length, retention "
             "by chapter, experiments and the scoreboard.",
    "library": "Library: the writing files (edit and save, or reset to the "
               "shipped one), what Dennis remembers (facts, used jokes, the "
               "recurring bits), memes with their labels, b-roll, sounds "
               "and the rooms with the kit doctor.",
    "settings": "Settings: the switches (memes in SHORTs, viewer questions, "
                "the voice room, the de-esser) and quiet mode, which apply "
                "at once with no restart; the health checks, disk space and "
                "failed renders. Keys and passwords are never shown there.",
    "activity": "Activity: everything the bot said, newest first, as in "
                "Telegram.",
    "commands": "Commands: every command the bot knows, as a form.",
}

# A video's workspace steps, in order (pinned to `panel_views.STEPS`).
STEP_GUIDE: dict[str, str] = {
    "data": "drop the refreshed workbook (dennis_data.xlsx); it shows the "
            "as-of date, freshness, key figures and warnings.",
    "angle": "LONGs only: copy the angle prompt into your own Claude chat, "
             "paste the angles back and pick one. The filing brief is here.",
    "write": "copy the full writing prompt (or download it) into your own "
             "Claude chat, then paste or drop the script back.",
    "check": "the script as numbered lines, every line editable in place "
             "with undo; the findings grouped by check and linked to their "
             "lines; the claims list, the cold read, Dennis's share of "
             "screen time alone and the estimated length.",
    "proof": "render the free proof (the free local voice, full picture), "
             "then watch it with chapter marks and frame-by-frame keys and "
             "note faults at a moment; the notes make a numbered list.",
    "approve": "the cost estimate, then Approve. This is where money is "
               "spent: one paid ElevenLabs voice per approved script.",
    "voice": "listen with the words lit up, redo a sentence (up to 10 per "
             "video, a few cents each), fix how a word is said, or stop "
             "the render.",
    "render": "the stage, percentage, time left, the latest log lines and "
              "Stop.",
    "upload": "by hand in YouTube Studio (copy buttons for the title, "
              "description, tags, pinned comment and chapters, and the "
              "Studio checklist with altered or synthetic content set to "
              "Yes), or with /publish, private or scheduled. Your Figma "
              "thumbnail goes in the slot.",
    "live": "the retention chart, where viewers left by sentence, "
            "corrections and the scoreboard.",
}

# What each check on the report looks at (pinned to the names `run_gates`
# records). "Blocks" means it can stop a render; every other one warns.
CHECKS: dict[str, str] = {
    "fact-check": "every number in the narration against the workbook",
    "on-screen": "figures written onto a plate against the workbook; blocks",
    "voice": "what the voice bible forbids",
    "phrasing": "machine-made phrasing from the editable list",
    "swearing": "strong swears past the limit (four in a LONG, never two "
                "in a minute, one in a SHORT, none in a title or the first "
                "ten seconds)",
    "joke-floor": "the jokes the writer listed: at least three in a SHORT, "
                  "about one a minute in a LONG with no long dry stretch, "
                  "and every listed one really said",
    "prompt-words": "the prompt's own words said aloud or printed on a "
                    "plate (\"the four-step valuation walk\", \"STEP 1\")",
    "copy": "a sentence repeating a voice bible example or a style "
            "reference word for word",
    "jokes": "a joke, analogy or callback already used on the channel, "
             "even reworded",
    "bits": "a recurring bit (Kev's tip, Dennis's old trade) back too soon, "
            "or both in one video",
    "chapters": "chapter types in the same order as one of the last three "
                "LONGs",
    "direction": "the delivery tags and the limits on using them",
    "confession": "the same admission told twice",
    "valuation": "the valuation chapter's four moves, in order; blocks on a "
                 "skipped third move",
    "budgets": "copy that does not fit the box the kit drew for it; blocks",
    "freshness": "a workbook too old to state its numbers as current",
    "audio": "sound files that are still synthesised placeholders",
    "prices": "whether the price chart is drawn from real prices",
    "kit": "what the design kit could not answer",
    "sameness": "this script against the ones already shipped; blocks only "
                "a script that is effectively an old one re-tickered",
    "pacing": "notes on rhythm; never blocks",
    "loops": "notes on the opening's open loops",
    "title": "the title package against the script",
    "skeptic": "the local model reading the script as a hostile investor, "
               "when asked for",
}

# Settings whose names say they are secret, or about a person. Left out of
# the settings drawer whole, before any value is read.
_SECRET_NAME = re.compile(
    r"key|token|secret|pass|cookie|credential|oauth|client|webhook|chat|"
    r"email|contact|agent|account|user", re.I)


def _view(core) -> SimpleNamespace:
    """What the page's view functions read off the panel, with no file ever
    linked: an answer carries text, not links."""
    return SimpleNamespace(core=core, settings=core.settings,
                           allowed=lambda _p: False)


def _jobs(core) -> list:
    from pipeline.jobs import JobStore

    store = core.queue.store if core.queue is not None else JobStore(core.settings)
    return store.all()


def _money(v) -> str:
    return "unreadable" if v is None else f"${v:,.2f}"


# --------------------------------------------------------------------------
# The drawers
# --------------------------------------------------------------------------

def status_text(core, _terms=()) -> str:
    """The status board: what is open, waiting, rendering, spent and on."""
    from bot.commands import NotifyPrefs
    from bot.panel_views import STEPS, current_step
    from pipeline.jobs import progress
    from pipeline.switches import rows
    from pipeline.video_state import all_states, inbox, inbox_text
    from pipeline.workspace import today_str

    s = core.settings
    titles = dict(STEPS)
    lines = [f"Today is {today_str()}."]
    banner = s.mock_banner()
    if banner:
        lines.append(banner)
    states = all_states(s)
    if states:
        lines.append(f"Videos worked on in the last 14 days ({len(states)}):")
        for st in states[:12]:
            fmt = "UPDATE" if st.update else (st.lane or st.fmt or "?").upper()
            lines.append(f"- {st.ticker} {fmt} {st.workdate}: waiting on the "
                         f"{titles.get(current_step(st), '?')} step")
    else:
        lines.append("No video has been worked on in the last 14 days.")
    items = inbox(s, states=states)
    if items:
        lines.append(inbox_text(items))
    est = {(st.ticker, st.workdate): st.est_render_min for st in states}
    jobs = sorted(_jobs(core), key=lambda j: j.updated_at, reverse=True)
    live = [j for j in jobs if j.status.value in ("queued", "running")]
    if live:
        lines.append("The render queue:")
        for j in live:
            p = progress({"status": j.status.value, "detail": j.detail,
                          "started_at": j.started_at},
                         est.get((j.ticker, j.workdate)))
            left = (f", about {round(p['eta_s'] / 60)} min left"
                    if p.get("eta_s") else "")
            lines.append(f"- {j.ticker} {j.kind.value}: {j.status.value}, "
                         f"{p['stage']} {p['pct']:.0f}%{left}")
    else:
        lines.append("Nothing is rendering or queued.")
    done = [j for j in jobs if j.status.value not in ("queued", "running")][:3]
    for j in done:
        line = f"Last: {j.ticker} {j.kind.value} {j.status.value} at {j.updated_at[:16]}"
        if j.error:
            line += f" ({j.error.splitlines()[0][:160]})"
        lines.append(line)
    try:
        mtd = core.ledger.mtd_spend_usd()
    except Exception:                                 # noqa: BLE001
        mtd = None
    lines.append(f"Voice spend this month: {_money(mtd)} of the "
                 f"{_money(s.monthly_spend_cap_usd)} cap.")
    sw = ", ".join(f"{r['title']} {'on' if r['on'] else 'off'}" for r in rows(s))
    quiet = NotifyPrefs(s).level() == "quiet"
    lines.append(f"Switches: {sw}; quiet mode {'on' if quiet else 'off'}; "
                 f"DENNIS_3D {(s.dennis_3d or 'off').lower()}.")
    return "\n".join(lines)


def video_text(core, ticker: str, workdate: str) -> str:
    """One video's workspace, step by step, as its screen shows it."""
    from bot.panel_views import video_view
    from pipeline.video_state import card_text, video_state
    from pipeline.workspace import Workspace

    view = video_view(_view(core), ticker, workdate)
    st = video_state(core.settings, Workspace(core.settings, ticker, workdate))
    lines = [card_text(st), "Its steps on the page:"]
    for step in view.get("steps", []):
        summary = f" — {step['summary']}" if step.get("summary") else ""
        lines.append(f"- {step['title']}: {step['status']}{summary}")
    report = view.get("check", {}) if isinstance(view.get("check"), dict) else {}
    for f in (report.get("findings") or [])[:12]:
        if isinstance(f, dict):
            where = f" (line {f['line']})" if f.get("line") else ""
            lines.append(f"  [{f.get('gate', '')}] {f.get('severity', '')}"
                         f"{where}: {str(f.get('message', ''))[:160]}")
    return "\n".join(lines)


def manual_text(_core=None, _terms=()) -> str:
    """How the bot is used: the page's screens, a video's steps, what each
    check on the report looks at, and what each switch does."""
    from bot.panel_views import STEPS
    from pipeline.switches import SWITCHES

    lines = ["THE PAGE (his main tool; Telegram is the remote):"]
    lines += [f"- {text}" for text in SCREENS.values()]
    lines.append("A VIDEO'S STEPS on its workspace, in order:")
    lines += [f"- {title}: {STEP_GUIDE[step]}" for step, title in STEPS]
    lines.append("THE CHECKS on a script's report (all warn unless it says "
                 "blocks):")
    lines += [f"- {name}: {what}" for name, what in CHECKS.items()]
    lines.append("THE SWITCHES on Settings (or /admin switch NAME on|off):")
    lines += [f"- {s.title} ({s.env}): {s.says}" for s in SWITCHES.values()]
    return "\n".join(lines)


def settings_text(core, terms=()) -> str:
    """Every setting that is not a secret, by its .env name. Those the
    question names come first (`recall.focus` keeps them); a setting that
    differs from the shipped default says so."""
    from pipeline.jobs import _secret_values

    s = core.settings
    secrets = [v for v in _secret_values(s) if v]
    out = []
    for name, f in type(s).model_fields.items():
        env = f.alias or name.upper()
        if _SECRET_NAME.search(name) or _SECRET_NAME.search(env):
            continue
        value = getattr(s, name, None)
        shown = str(value)
        if any(sec in shown for sec in secrets):
            continue
        if len(shown) > 90:
            shown = shown[:90] + "…"
        changed = "" if value == f.default else " (changed from the default)"
        out.append(f"{env} = {shown}{changed}")
    return "Settings (.env), keys and passwords left out:\n" + "\n".join(out)


def _section(view: dict, key: str):
    part = view.get(key)
    if isinstance(part, dict) and "error" in part and len(part) == 1:
        return None
    return part


def writing_text(core, _terms=()) -> str:
    from bot.panel_pages import _writing

    rows = _writing(_view(core))
    lines = ["His writing files (Library > Writing; each can be edited, "
             "saved, or reset to the shipped one):"]
    for r in rows:
        state = "edited by him" if r["edited"] else "the shipped one"
        lines.append(f"- {r['title']} ({r['name']}): {state}, "
                     f"{len(r['text']):,} characters")
    return "\n".join(lines)


def writing_file_text(core, name: str) -> str:
    from pipeline import writing_files as wf

    s = core.settings
    state = "his edited copy" if wf.is_edited(s, name) else "the shipped copy"
    return f"({state})\n{wf.read_file(s, name)}"


def memory_text(core, _terms=()) -> str:
    from bot.panel_pages import _bits, _book

    view = _view(core)
    facts, jokes, bits = _book(view, "facts"), _book(view, "jokes"), _bits(view)
    lines = [f"What Dennis has said about himself ({len(facts)} facts; a "
             f"later video never contradicts them):"]
    lines += [f"- {r['text']}" + (f" ({r['ticker']} {r['workdate']})"
                                  if r["ticker"] else "") for r in facts]
    lines.append(f"Jokes, analogies and callbacks already used ({len(jokes)}, "
                 f"newest last):")
    lines += [f"- {r['text']}" for r in jokes[-40:]]
    lines.append("The recurring bits (LONGs only; Kev's tip and the old "
                 "trade come back every 6 to 8 LONGs, never both in one):")
    for b in bits["bits"]:
        lines.append(f"- {b['name']}: {b['since']} LONG(s) since it last ran; "
                     f"this time it waits {b['gap']}"
                     + (", so it is due" if b["overdue"] >= 0 else ""))
    if bits.get("due"):
        lines.append(f"Due next: {bits['due']}.")
    return "\n".join(lines)


def memes_text(core, _terms=()) -> str:
    from bot.panel_pages import _memes

    m = _memes(_view(core))
    s = core.settings
    lines = [f"The meme library: {len(m['rows'])} labelled "
             f"(memes in SHORTs are {'on' if s.short_meme else 'off'}; a LONG "
             f"uses at most two, none shown in the last six videos):"]
    for r in m["rows"]:
        lately = " [used lately]" if r["recent"] else ""
        lines.append(f"- {r['stem']}: {', '.join(r['tags'])} — use when "
                     f"{r['use_when']}{lately}")
    if m["unlabelled"]:
        lines.append("Pictures with no label yet (never used until "
                     "labelled): " + ", ".join(m["unlabelled"]))
    return "\n".join(lines)


def broll_text(core, _terms=()) -> str:
    from bot.panel_pages import _broll

    b = _broll(_view(core))
    keys = Counter(c["key"] for c in b["clips"])
    lines = [f"B-roll: {len(b['clips'])} owned clips covering "
             f"{len(keys)} of the {b['keys']} palette subjects."]
    lines += [f"- {k}: {n} clip(s)" for k, n in sorted(keys.items())]
    if b["without"]:
        lines.append("Subjects with no owned clip (fetched from Pexels when "
                     "needed): " + ", ".join(b["without"]))
    return "\n".join(lines)


def sounds_text(core, _terms=()) -> str:
    from bot.panel_pages import _sounds

    rows = _sounds(_view(core))
    by_dir: dict[str, list[dict]] = {}
    for r in rows:
        by_dir.setdefault(r["dir"], []).append(r)
    lines = ["Sounds and music (Library > Sounds):"]
    for d, items in by_dir.items():
        held = [r["name"] for r in items if r["placeholder"]]
        lines.append(f"- {d}: {len(items)} file(s)"
                     + (f", {len(held)} still a synthesised placeholder "
                        f"({', '.join(held[:12])})" if held else ""))
        lines.append("  " + ", ".join(r["name"] for r in items[:40]))
    return "\n".join(lines)


def rooms_text(core, _terms=()) -> str:
    from bot.panel_pages import _rooms

    rows = _rooms(_view(core))
    lines = [f"The 3D rooms: {len(rows)} rendered."]
    for aspect in sorted({r["aspect"] for r in rows}):
        mine = [r for r in rows if r["aspect"] == aspect]
        hours = Counter(r["hour"] or "any" for r in mine)
        seasons = Counter(r["season"] or "any" for r in mine)
        lines.append(f"- {aspect}: {len(mine)}; hours "
                     f"{dict(sorted(hours.items()))}; seasons "
                     f"{dict(sorted(seasons.items()))}")
        lines.append("  " + ", ".join(r["key"] for r in mine[:60]))
    return "\n".join(lines)


def health_text(core, _terms=()) -> str:
    from bot.panel_pages import _disk, _failures, _preflight

    view = _view(core)
    lines = ["The health checks (Settings > Health):"]
    for r in _preflight(view):
        lines.append(f"- {r['name']}: {r['state']} — {r['detail'][:200]}")
    for d in _disk(view):
        lines.append(f"Disk ({d['name']}): {d['free_gb']} GB free of "
                     f"{d['total_gb']} GB.")
    fails = _failures(view)
    if fails:
        lines.append("Failed renders, newest first:")
        lines += [f"- {f['ticker']} {f['kind']} {f['at'][:16]}: "
                  f"{f['error'].splitlines()[0][:200] if f['error'] else '?'}"
                  for f in fails]
    else:
        lines.append("No failed renders on record.")
    return "\n".join(lines)


def ideas_text(core, _terms=()) -> str:
    from bot.panel_pages import ideas_view

    v = ideas_view(_view(core))
    lines = []
    backlog = _section(v, "backlog") or []
    lines.append(f"The idea backlog ({len(backlog)}, best first):")
    lines += [f"- {i['ticker']} ({i['lane'] or 'any lane'}, from "
              f"{i['source']}): {i['reason'][:140]}" for i in backlog[:20]]
    watch = _section(v, "watch") or []
    lines.append("Watch list: " + (", ".join(map(str, watch)) or "empty"))
    earnings = _section(v, "earnings") or []
    if earnings:
        lines.append("Earnings dates: " + ", ".join(
            f"{e['ticker']} {e['date']} {e['when']}" for e in earnings))
    screen = _section(v, "screen") or {}
    rows = screen.get("rows") or []
    if rows:
        lines.append("The last screener run:")
        lines += [f"- {r['ticker']} ({r['lane']}): "
                  f"{'; '.join(r['reasons'])[:140]}" for r in rows[:10]]
    return "\n".join(lines)


def calendar_text(core, _terms=()) -> str:
    from bot.panel_pages import calendar_view

    v = calendar_view(_view(core))
    lines = [f"The calendar, {v['title']}:"]
    gaps = []
    for d in v["days"]:
        for it in d.get("items") or []:
            what = ("scheduled" if it.get("pending") else
                    it.get("privacy") or "out")
            lines.append(f"- {d['date']}: {it.get('ticker', '')} "
                         f"{it.get('fmt', '')} {what} — "
                         f"{str(it.get('title', ''))[:80]}")
        if d.get("gap"):
            gaps.append(d["date"][-2:])
    if gaps:
        lines.append(f"Days ahead with nothing going out: {', '.join(gaps)}.")
    ready = v.get("ready") or []
    if ready:
        lines.append("Finished, not yet uploaded: " + ", ".join(
            f"{r['ticker']} {r['fmt']} {r['workdate']}" for r in ready))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The cabinet
# --------------------------------------------------------------------------

# A word a question uses when it wants each drawer. Four letters or more:
# shorter words never open one (`Drawer.score`).
_WORDS = {
    "manual": ("page", "screen", "screens", "step", "steps", "button",
               "check", "checks", "finding", "findings", "warning",
               "warnings", "gate", "gates", "workflow", "process", "help",
               "menu", "work", "works", "use", "switch", "switches", "tab"),
    "settings": ("setting", "settings", "config", "configuration", "env",
                 "environment", "fps", "frame", "resolution", "model",
                 "ollama", "gemma", "delivery", "batch", "timeout", "limit",
                 "default", "option", "options", "outlines"),
    "writing": ("writing", "file", "files", "list", "lists", "edited",
                "prompt", "prompts"),
    "memory": ("fact", "facts", "joke", "jokes", "remember", "remembers",
               "memory", "bit", "bits", "segment", "segments", "kev",
               "trade", "recurring", "callback", "callbacks", "analogy"),
    "memes": ("meme", "memes", "image", "images", "picture", "pictures",
              "gif", "gifs", "label", "labels", "labelled"),
    "broll": ("b-roll", "broll", "footage", "clip", "clips", "stock",
              "pexels"),
    "sounds": ("sound", "sounds", "sfx", "effect", "effects", "music",
               "score", "audio", "theme", "freesound", "placeholder",
               "placeholders", "footstep", "footsteps"),
    "rooms": ("room", "rooms", "angle", "angles", "kit", "plate", "plates",
              "background", "night", "dusk", "season", "seasons", "hour",
              "camera", "blender", "set"),
    "health": ("health", "healthy", "broken", "error", "errors", "fail",
               "failed", "failure", "failures", "preflight", "disk", "space",
               "problem", "problems", "wrong", "ready", "setup", "working"),
    "ideas": ("idea", "ideas", "backlog", "watchlist", "watch", "earnings",
              "screener", "screen", "trending", "next"),
    "calendar": ("calendar", "schedule", "scheduled", "publish", "published",
                 "publishing", "week", "month", "date", "gap", "gaps", "free",
                 "upload", "uploaded", "youtube", "going"),
}
_FILE_WORDS = {
    "voice_bible": ("bible", "tone", "voice"),
    "dennis_story": ("story", "backstory", "family", "linda", "gary",
                     "megan", "nan", "life", "history", "character", "kev"),
    "ai_phrases": ("phrase", "phrases", "phrasing", "machine", "slop"),
    "style_references": ("style", "reference", "references", "benjamin"),
    "pronunciations": ("pronunciation", "pronunciations", "pronounce",
                       "pronounced", "said", "say", "spoken", "spell"),
}

_CABINET = (
    ("manual", "How the bot is used: its page, steps, checks and switches",
     manual_text, "the page"),
    ("settings", "The bot's settings", settings_text, ".env"),
    ("writing", "His writing files", writing_text, "Library > Writing"),
    ("memory", "What Dennis remembers", memory_text, "Library > Memory"),
    ("memes", "The meme library", memes_text, "Library > Memes"),
    ("broll", "The b-roll library", broll_text, "Library > B-roll"),
    ("sounds", "The sounds and music", sounds_text, "Library > Sounds"),
    ("rooms", "The 3D rooms", rooms_text, "Library > Rooms"),
    ("health", "The health checks", health_text, "Settings > Health"),
    ("ideas", "Ideas, the watch list and earnings", ideas_text, "Ideas"),
    ("calendar", "This month's calendar", calendar_text, "Calendar"),
)


def drawers(core) -> list[Drawer]:
    """Every drawer `/ask` may open, nothing built until it is opened."""
    from pipeline import writing_files as wf
    from pipeline.video_state import all_states

    out = [Drawer("status", "The bot right now: videos, queue, spend, switches",
                  (), lambda t: status_text(core, t), always=True,
                  place="Home")]
    for name, title, fn, place in _CABINET:
        out.append(Drawer(name, title, _WORDS[name],
                          (lambda f: lambda t: f(core, t))(fn), place=place))
    for name in wf.WRITING_FILES:
        out.append(Drawer(
            f"writing:{name}", f"{wf.TITLES.get(name, name)} (his writing file)",
            _FILE_WORDS.get(name, tuple(name.split("_"))),
            (lambda n: lambda t: writing_file_text(core, n))(name),
            place="Library > Writing"))
    newest: dict[str, str] = {}
    for st in all_states(core.settings):
        if st.workdate > newest.get(st.ticker, ""):
            newest[st.ticker] = st.workdate
    for ticker, workdate in sorted(newest.items()):
        out.append(Drawer(
            f"video:{ticker}", f"The {ticker} video of {workdate}", (),
            (lambda t_, d_: lambda t: video_text(core, t_, d_))(ticker, workdate),
            ticker=ticker, place=f"its workspace ({ticker} {workdate})"))
    return out
