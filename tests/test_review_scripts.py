"""Findings from the full review of the operator's scripts.

Each is run the way the operator runs it, as a subprocess, against a
throwaway tree. Nothing here touches the network or spends.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _run(script: str, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
           "MOCK_MODE": "true"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, env=env, cwd=ROOT,
                          timeout=180)


def test_regenerating_placeholders_keeps_a_fetched_sound(tmp_path,
                                                          monkeypatch):
    """Every update reran this and turned a real effect back into a sine
    sweep that SOURCES.json still called real."""
    spec = importlib.util.spec_from_file_location(
        "_gen_assets_review", SCRIPTS / "gen_assets.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", ["gen_assets.py"])
    spec.loader.exec_module(mod)
    mod.ASSETS = tmp_path
    (tmp_path / "sfx").mkdir()
    real = tmp_path / "sfx" / "cash_register.wav"
    real.write_bytes(b"a real recording")
    mod.gen_sfx()
    assert real.read_bytes() == b"a real recording"
    assert "cash_register.wav" in mod.KEPT
    assert (tmp_path / "sfx" / "whoosh.wav").is_file()


def test_no_music_is_paid_for_while_the_voice_is_mocked(tmp_path):
    got = _run("make_score.py", "--confirm", "--out", str(tmp_path / "score"),
               MOCK_MODE="false", MOCK_TTS="true", ELEVENLABS_API_KEY="k",
               STATE_DIR=str(tmp_path / "state"))
    assert got.returncode == 2, got.stdout + got.stderr
    assert "MOCK_TTS" in got.stderr


def test_freshness_reads_the_workbook_it_was_given(tmp_path):
    """A browser-renamed "dennis_data (1).xlsx" was UNREADABLE, and with an
    older export beside it the verdict was about that other file."""
    fixture = ROOT / "fixtures" / "company_data" / "dennis_data.xlsx"
    named = tmp_path / "dennis_data (1).xlsx"
    shutil.copy(fixture, named)
    got = _run("check_freshness.py", str(named),
               STATE_DIR=str(tmp_path / "state"))
    assert "UNREADABLE" not in got.stderr, got.stderr
    assert "as_of_date" in got.stdout


def test_the_state_archive_is_owner_only_and_restores_in_place(tmp_path):
    """It holds the channel's refresh token, and with STATE_DIR not named
    "state" the printed restore line made a new directory."""
    state = tmp_path / "dennis_state"
    state.mkdir()
    (state / "spend.json").write_text('{"2026-10": {"usd": 1.0}}',
                                      encoding="utf-8")
    token = state / "youtube.json"
    token.write_text("{}", encoding="utf-8")
    token.chmod(0o600)
    out = tmp_path / "backups"
    got = _run("backup_state.py", "--state", str(state), "--out", str(out))
    assert got.returncode == 0, got.stdout + got.stderr
    archive = next(out.glob("state-*.tar.gz"))
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    with tarfile.open(archive) as tar:
        assert "dennis_state/spend.json" in tar.getnames()
    assert f"-C {tmp_path}" in got.stdout


def test_an_unknown_sample_name_is_refused():
    got = _run("render_samples.py", "shorts")
    assert got.returncode != 0
    assert "unknown sample" in got.stderr
