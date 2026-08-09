"""The README's command reference matches the commands the bot registers.

A hand-written list of commands is wrong the first time one is added, and its
failure mode is the worst kind: an operator reading documentation that says
the bot can do something it cannot, or — the case that actually happened —
using `/long` on a covered name for months because nothing told them `/update`
existed.

Every other catalog in this repo is generated from the thing it describes for
exactly this reason. A README cannot be generated at fill time, so it is
pinned instead, in BOTH directions: a command with no row fails, and a row
with no command fails.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
HANDLERS = ROOT / "bot" / "handlers.py"

# Registered, but deliberately not in the reference tables.
#   `start` is an alias of `help` and shares its row.
_ALIASED = {"start"}


def _registered() -> set[str]:
    """Every command name passed to a CommandHandler."""
    src = HANDLERS.read_text(encoding="utf-8")
    names: set[str] = set()
    for arg in re.findall(r"CommandHandler\(\s*(\[[^\]]*\]|\"[a-z_]+\")", src):
        names |= set(re.findall(r'"([a-z_]+)"', arg))
    return names


def _documented() -> set[str]:
    """Every `/command` named in the first cell of a reference table row."""
    text = README.read_text(encoding="utf-8")
    start = text.index("## Command reference")
    end = text.index("### Things that are not commands", start)
    names: set[str] = set()
    for line in text[start:end].splitlines():
        if not line.startswith("| `/"):
            continue
        cell = line.split("|")[1]
        names |= set(re.findall(r"/([a-z_]+)", cell))
    return names


def test_every_registered_command_is_documented():
    missing = _registered() - _ALIASED - _documented()
    assert not missing, (
        f"the bot registers {sorted(missing)} and the README does not "
        f"mention them — add a row to the command reference")


def test_the_reference_invents_nothing():
    extra = _documented() - _registered()
    assert not extra, (
        f"the README documents {sorted(extra)}, which the bot does not "
        f"register — an operator reading this would type a command that "
        f"does nothing")


def test_the_reference_is_not_empty():
    """A parser that silently matched nothing would make both tests pass."""
    assert len(_documented()) >= 25, f"only found {len(_documented())} rows"
    assert "update" in _documented()
    assert "render" in _documented()


def test_the_help_text_and_the_readme_agree_on_what_exists():
    """The two places an operator looks. They may differ in DETAIL — the help
    text is a cheat sheet and the README is the reference — but a command in
    one and absent from the other means one of them is stale."""
    from bot.handlers import HELP_TEXT

    in_help = set(re.findall(r"^/([a-z_]+)", HELP_TEXT, re.MULTILINE))
    documented = _documented()
    assert not (in_help - documented), \
        f"in the help text, missing from the README: {sorted(in_help - documented)}"
