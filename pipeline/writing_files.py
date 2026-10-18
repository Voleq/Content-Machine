"""The writing lists the operator edits, with the shipped defaults beneath.

Three files steer what the writer is told and what the checks look for: the
machine-phrasing list (S1), the style references the copy check reads (S2)
and Dennis's story (S8). A fourth steers the voice: how a word is said (A5). Each ships as a default under `assets/writing/` and
is edited on the panel, and an edit is written to `state/writing/` rather
than over the default. Two reasons, and they are the design:

* `assets/` is the checkout. An edit written there is a dirty working tree
  the next `git pull` refuses, or worse, merges.
* The default stays readable, so "reset" is deleting his copy, never
  remembering what the shipped text used to say.

The cost is that a default improved upstream does not reach a list he has
already edited. That is the right way round: his edit is the newer opinion.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

# name -> file name, the same under `assets/writing/` and `state/writing/`.
WRITING_FILES: dict[str, str] = {
    "ai_phrases": "ai_phrases.txt",
    "style_references": "style_references.txt",
    "dennis_story": "dennis_story.md",
    # How a word is said to ElevenLabs (A5) — never what the captions show.
    "pronunciations": "pronunciations.txt",
}

_REGEX_PREFIX = "re:"


def _filename(name: str) -> str:
    try:
        return WRITING_FILES[name]
    except KeyError:
        raise KeyError(f"no writing file called {name!r}") from None


def default_path(settings: Settings, name: str) -> Path:
    return settings.assets_dir / "writing" / _filename(name)


def edited_path(settings: Settings, name: str) -> Path:
    return settings.state_dir / "writing" / _filename(name)


def is_edited(settings: Settings, name: str) -> bool:
    return edited_path(settings, name).exists()


def read_file(settings: Settings, name: str) -> str:
    """His copy when he has one, else the shipped default, else ""."""
    for path in (edited_path(settings, name), default_path(settings, name)):
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as e:
            log.warning("writing file %s unreadable (%s)", path, e)
    return ""


def write_file(settings: Settings, name: str, text: str) -> Path:
    """Save his edit. Never touches the shipped default."""
    path = edited_path(settings, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def reset(settings: Settings, name: str) -> bool:
    """Back to the shipped default. True when there was an edit to drop."""
    path = edited_path(settings, name)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def list_lines(settings: Settings, name: str) -> list[str]:
    """The file as a list: stripped, without blanks or `#` comments."""
    out = []
    for line in read_file(settings, name).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def phrase_patterns(settings: Settings,
                    name: str = "ai_phrases") -> list[tuple[str, "re.Pattern[str]"]]:
    """(the line as written, its pattern) for every usable line.

    A line starting `re:` is a regular expression, compiled as given. Any
    other line is a phrase, matched case-insensitively as whole words, so
    "delve" does not fire inside "shelved". A line that does not compile is
    skipped with a warning: one typo on the panel must not switch the whole
    check off, and an exception here would.
    """
    out: list[tuple[str, re.Pattern[str]]] = []
    for line in list_lines(settings, name):
        if line.lower().startswith(_REGEX_PREFIX):
            source = line[len(_REGEX_PREFIX):].strip()
            try:
                out.append((source, re.compile(source, re.IGNORECASE)))
            except re.error as e:
                log.warning("%s: skipped a pattern that does not compile "
                            "(%r: %s)", name, source, e)
            continue
        body = re.escape(line)
        lead = r"\b" if re.match(r"\w", line) else ""
        tail = r"\b" if re.search(r"\w$", line) else ""
        out.append((line, re.compile(lead + body + tail, re.IGNORECASE)))
    return out
