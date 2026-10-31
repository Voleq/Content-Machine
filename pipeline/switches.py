"""The switches he flips on the page, or with `/admin switch NAME on|off`.

Four settings ship off and wait on something only he can judge: his ear on
the first paid voice (the room, the de-esser), the channel having viewers
(their questions), and whether a SHORT's verdict wants its meme back. Each
is a plain `Settings` field and keeps its `.env` name, so a box that set one
there still has it.

A flip is written to `state/switches.json` and set on the running bot's
settings at once: the next render, prompt or weekly read sees it with no
restart. At start the file is laid over `.env`, so the page's last word wins
over a line he wrote once and forgot. Only these: a key, a path or the 3D
Dennis is never a switch. The fifth, stockanalysis.com, ships on: it is the
research source he asked for (30 Oct 2026), and off is for a day the site
misbehaves.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SWITCH_FILE = "switches.json"


@dataclass(frozen=True)
class Switch:
    name: str        # the Settings field
    env: str         # its .env name
    title: str
    says: str        # one plain sentence for the page and /help


SWITCHES: dict[str, Switch] = {s.name: s for s in (
    Switch("short_meme", "SHORT_MEME", "Memes in SHORTs",
           "Lays a library meme over the last second and a half of a SHORT's "
           "verdict. Off since 10 October: nothing the voice says points at it."),
    Switch("viewer_questions", "VIEWER_QUESTIONS", "Viewer questions",
           "Reads the top comments once a week and lets the LONG's writer answer "
           "one or two in a closing section. Leave it off until the channel has "
           "viewers."),
    Switch("voice_room", "VOICE_ROOM", "The voice in the room",
           "A faint early echo under the voice, so it sounds like his flat rather "
           "than a booth. Hear /voice compare on a paid voice first."),
    Switch("voice_deess", "VOICE_DEESS", "De-esser",
           "Softens the sharp s sounds in the voice. Hear /voice compare on a "
           "paid voice first."),
    Switch("stockanalysis_enabled", "STOCKANALYSIS", "stockanalysis.com",
           "Reads the news around a move, the earnings call, the quarters, the "
           "analysts and the day's movers off stockanalysis.com for every "
           "prompt. Off, nothing is asked and the prompts say so."),
)}


def _path(settings) -> Path:
    return Path(settings.state_dir) / SWITCH_FILE


def saved(settings) -> dict[str, bool]:
    """What the page last set: known names with a true/false only."""
    try:
        raw = json.loads(_path(settings).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("switches file unreadable (%s); .env stands", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in SWITCHES and isinstance(v, bool)}


def apply(settings) -> dict[str, bool]:
    """Lay the saved switches over `settings`; returns what it set."""
    out = saved(settings)
    for name, on in out.items():
        setattr(settings, name, on)
    return out


def set_switch(settings, name: str, on: bool) -> Switch:
    """Flip one switch now and keep it. KeyError for a name that is not one."""
    name = name.strip().lower().replace("-", "_")
    if name not in SWITCHES:
        # The .env spelling is accepted too: it is what the docs print.
        by_env = {s.env.lower(): s.name for s in SWITCHES.values()}
        name = by_env.get(name, name)
    if name not in SWITCHES:
        raise KeyError(name)
    values = saved(settings)
    values[name] = bool(on)
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(values, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    setattr(settings, name, bool(on))
    return SWITCHES[name]


def rows(settings) -> list[dict]:
    """Every switch as the page shows it."""
    kept = saved(settings)
    return [{"name": s.name, "env": s.env, "title": s.title, "says": s.says,
             "on": bool(getattr(settings, s.name, False)),
             "from_page": s.name in kept} for s in SWITCHES.values()]
