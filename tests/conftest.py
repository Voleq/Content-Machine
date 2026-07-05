"""Shared test fixtures.

The whole suite runs offline in MOCK_MODE. A guard fixture makes any
accidental real HTTP call fail loudly.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402

FIXTURES = ROOT / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Isolated settings: runtime dirs under tmp, mock mode forced on."""
    s = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp_path / "workspace",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        _env_file=None,
    )
    s.ensure_runtime_dirs()
    return s


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture()
def short_valid_json() -> str:
    return (FIXTURES / "scripts" / "short_valid.json").read_text()


@pytest.fixture()
def long_valid_text() -> str:
    return (FIXTURES / "scripts" / "long_valid.txt").read_text()


@pytest.fixture()
def alignment_sample() -> dict:
    return json.loads((FIXTURES / "tts" / "alignment_sample.json").read_text())


@pytest.fixture()
def workspace(settings: Settings) -> Path:
    """A prepared workspace dir for EXMPL with the fixture data export."""
    ws = settings.workspace_dir / "EXMPL" / "2026-07-01"
    ws.mkdir(parents=True)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    return ws


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail any test that tries to open a real socket connection."""
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address):  # noqa: ANN001
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address)
        raise AssertionError(f"network call attempted in tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
