"""The diagnostic scripts an operator runs before a first live video (P5/P10).

These are not unit tests of library functions. They are the operator's
commands, and what a command is worth is its exit code — `scripts/check_sfx.py`
saying PASS while the audio gate would block a render is a worse state than
having no script at all, because it moves the discovery to the render.

So each one is run as a subprocess, both ways, against a throwaway tree.
Nothing here touches the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _run(script: str, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
           "MOCK_MODE": "true"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, env=env, cwd=ROOT,
                          timeout=180)


# --------------------------------------------------------------------------
# Every preflight script exists and behaves like one.
# --------------------------------------------------------------------------

# Grown by the commit that adds each script, so a name here always points at
# something that exists.
PREFLIGHT = ("check_sfx.py", "check_freshness.py", "check_llm_context.py")


@pytest.mark.parametrize("name", PREFLIGHT)
def test_the_preflight_script_exists_and_is_runnable(name):
    """The README's preflight list names these. A step that points at a
    script that is not there is worse than a step that is missing."""
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is named in the preflight and absent"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env python3"), f"{name} has no shebang"
    assert '"""' in text.split("\n", 1)[1][:400], f"{name} has no docstring"
    # It must be importable-clean: a syntax error here is discovered by the
    # operator at the worst possible moment.
    import ast

    ast.parse(text)


# --------------------------------------------------------------------------
# check_freshness.py — the parser against the operator's real locale.
# --------------------------------------------------------------------------


def _workbook_with_as_of(dest: Path, value) -> Path:
    """The fixture workbook with its as-of cell rewritten."""
    from openpyxl import load_workbook

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "fixtures" / "company_data" / "dennis_data.xlsx", dest)
    wb = load_workbook(dest)
    ws = wb["Snapshot"]
    for row in ws.iter_rows():
        for cell in row:
            if str(cell.value).strip() == "as_of_date":
                ws.cell(row=cell.row, column=4, value=value)
    wb.save(dest)
    wb.close()
    return dest


def test_a_fresh_workbook_passes_the_freshness_check(tmp_path):
    """The passing case has to be reachable, or the script is just a wall."""
    import datetime as dt

    today = dt.date.today().isoformat()
    book = _workbook_with_as_of(tmp_path / "ws" / "dennis_data.xlsx", today)
    got = _run("check_freshness.py", str(book))
    assert got.returncode == 0, got.stdout + got.stderr
    assert "PASS" in got.stdout
    assert today in got.stdout


def test_a_stale_workbook_is_reported_as_stale_not_as_unreadable(tmp_path):
    """Two different problems with two different fixes, and the message the
    gate gives on its own does not distinguish them well enough to act on."""
    book = _workbook_with_as_of(tmp_path / "ws" / "dennis_data.xlsx",
                                "2020-01-01")
    got = _run("check_freshness.py", str(book))
    assert got.returncode == 1
    assert "2020-01-01" in got.stdout
    assert "READ fine" in got.stderr, "a stale date was reported as unparseable"
    assert "Refresh the workbook" in got.stderr


def test_a_date_the_parser_cannot_read_says_so_and_lists_what_it_accepts(
        tmp_path):
    """`DATA_STALE_BLOCKS` defaults to true and an unreadable date blocks
    too, so a locale the parser has never seen walls the operator off from
    their own pipeline with a message about staleness. This is the script's
    whole reason to exist: the sheet is whatever Capital IQ wrote."""
    book = _workbook_with_as_of(tmp_path / "ws" / "dennis_data.xlsx",
                                "10.IX.2026")
    got = _run("check_freshness.py", str(book))
    assert got.returncode == 1
    assert "NOTHING" in got.stdout
    assert "could not be PARSED" in got.stderr
    assert "%Y-%m-%d" in got.stderr, "it does not say what it would accept"
    assert "rather than turning the gate off" in got.stderr


@pytest.mark.parametrize("shape", [
    "2026-09-10",        # ISO, what the template asks for
    "09/10/2026",        # US-first
    "10/09/2026",        # day-first, a European locale
    "10-Sep-2026",
    "Sep 10, 2026",
    "10.09.2026",
    46276,               # a raw Excel serial
])
def test_the_shapes_a_capital_iq_export_might_write_all_read(tmp_path, shape):
    """Each of these is a real thing a locale writes into that cell, and the
    gate blocks on any it cannot read."""
    book = _workbook_with_as_of(tmp_path / f"ws{shape}" / "dennis_data.xlsx",
                                shape)
    got = _run("check_freshness.py", str(book))
    assert "NOTHING" not in got.stdout, (
        f"{shape!r} is unreadable to the gate:\n{got.stdout}{got.stderr}")


def test_the_script_explains_itself_with_no_arguments():
    got = _run("check_freshness.py")
    assert got.returncode == 2
    assert "check_freshness.py" in got.stderr


# --------------------------------------------------------------------------
# check_llm_context.py — the one that needs a live daemon.
# --------------------------------------------------------------------------


def test_the_context_check_reports_an_unreachable_daemon_as_unproven():
    """It needs a live Ollama, which the suite does not have. What matters
    offline is that it does not claim a PASS it cannot know: "nothing is
    proven" and "the marker came back" must never be confusable."""
    got = _run("check_llm_context.py", OLLAMA_BASE_URL="http://127.0.0.1:1")
    assert got.returncode == 2, got.stdout + got.stderr
    assert "Nothing is proven" in got.stdout or "Nothing is proven" in got.stderr
    assert "OK —" not in got.stdout
