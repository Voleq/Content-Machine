"""The README, pinned against the code it describes.

Prose drifts and nothing goes red. This file went away with the old kit and
the README kept describing it for a fortnight: `kit.py` and its 387 assets,
`restyle_dark_cards.py`, the twelve marks, `[ASSET]` blocking, ~190 tests. All
of it read as fact and none of it was.

What is cheap to pin is pinned. A command with no row and a row with no
command both fail, and every path in the repository map has to exist.

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


# --------------------------------------------------------------------------
# The repository map.
# --------------------------------------------------------------------------

# What counts as a file in the map. A head with none of these and no trailing
# slash is prose — the second line of a wrapped description, or the comma list
# under `assets/`.
_SUFFIXES = (".py", ".js", ".json", ".md", ".xlsx", ".txt", ".sh")


def _mapped_paths() -> list[str]:
    """Every path the repository map names, as repo-relative strings.

    The map is a code block of `path<spaces>description` lines, indented to
    show nesting: a two-space indent under `pipeline/` is `pipeline/<name>`.
    A head ending in `/` is a directory and becomes the prefix for what is
    indented under it; a head with a known suffix is a file; anything else is
    the continuation of a description and is skipped.
    """
    text = README.read_text(encoding="utf-8")
    start = text.index("## Repository map")
    block = text[text.index("```", start) + 3:]
    block = block[:block.index("```")]

    out: list[str] = []
    stack: list[tuple[int, str]] = []          # (indent, prefix)
    for line in block.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        head = line.strip().split(" ")[0].split(",")[0]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        prefix = stack[-1][1] if stack else ""
        if head.endswith("/"):
            if "|" in head:                    # `workspace|cache|state/`
                continue
            stack.append((indent, prefix + head))
            out.append(prefix + head.rstrip("/"))
        elif head.endswith(_SUFFIXES):
            out.append(prefix + head)
    return out


def test_the_repository_map_names_things_that_exist():
    """A map that points at a deleted file sends a reader hunting.

    `restyle_dark_cards.py` and `export_design_kit.py` were in it for a
    fortnight after they were deleted, next to `kit.py`, which had been
    replaced by a registry with a different shape.
    """
    missing = []
    for path in _mapped_paths():
        if "*" in path:                        # `templates/master_prompt_*.md`
            if not list(ROOT.glob(path)):
                missing.append(path)
        elif not (ROOT / path).exists():
            missing.append(path)
    assert not missing, (
        f"the repository map names {missing}, which are not in the tree")


def test_the_map_parser_finds_the_files_it_should():
    """A parser that matched nothing would make the test above vacuous."""
    paths = _mapped_paths()
    assert len(paths) >= 40, f"only parsed {len(paths)} paths out of the map"
    for expected in ("config.py", "pipeline/plates.py", "pipeline/compose.py",
                     "bot/handlers.py", "scripts/ingest_kit.py"):
        assert expected in paths, f"{expected} is not in the parsed map"


def test_the_map_would_catch_a_deleted_file():
    """The check itself, checked: a path that is not there must fail."""
    assert not (ROOT / "pipeline" / "kit.py").exists()
    assert "pipeline/kit.py" not in _mapped_paths()


def test_the_readme_does_not_describe_the_kit_that_was_deleted():
    """Named things, because a stale name reads as fact.

    Each of these was in the README while the thing it named was gone: the
    old registry module, its asset count, the marks family the scribbles used
    to come from, the two build scripts, and the tag that used to block.
    """
    text = README.read_text(encoding="utf-8")
    # Anchored so `ingest_kit.py` does not read as `kit.py`.
    for gone in (r"(?<![\w_])kit\.py", r"(?<![\w_])kit_frames\.py",
                 "restyle_dark_cards", "export_design_kit", "387 assets",
                 r"\[DOODLE", r"(?<![\w_])doodles\.py", r"\[ASSET\]"):
        assert not re.search(gone, text), f"the README still describes {gone!r}"


def test_the_help_text_and_the_readme_agree_on_what_exists():
    """The two places an operator looks. They may differ in DETAIL — the help
    text is a cheat sheet and the README is the reference — but a command in
    one and absent from the other means one of them is stale."""
    from bot.handlers import HELP_TEXT

    in_help = set(re.findall(r"^/([a-z_]+)", HELP_TEXT, re.MULTILINE))
    documented = _documented()
    assert not (in_help - documented), \
        f"in the help text, missing from the README: {sorted(in_help - documented)}"
