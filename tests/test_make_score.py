"""scripts/make_score.py: the paid score is never paid for twice."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("make_score", ROOT / "scripts" / "make_score.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["make_score"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Ledger:
    def __init__(self):
        self.paid = []

    def record_tts(self, usd, **_):
        self.paid.append(usd)


def test_a_paid_piece_whose_encode_fails_is_kept_and_encoded_next_time(tmp_path, monkeypatch):
    ms = _script()
    piece = ms.Piece(name="bed-a", prompt="calm", length_ms=60_000, files=("bed-a.m4a",))
    calls = []
    monkeypatch.setattr(ms, "generate", lambda p, s: calls.append(p.name) or (b"MP3", "song-1"))
    monkeypatch.setattr(ms, "save_sources", lambda out, known: None)

    def broken(src, dest, **_):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(ms, "_level", broken)
    ledger = _Ledger()
    assert ms._make([piece], tmp_path, {}, None, ledger, "creator") == 1
    assert calls == ["bed-a"] and len(ledger.paid) == 1
    assert (tmp_path / ".bed-a.paid.mp3").read_bytes() == b"MP3"

    monkeypatch.setattr(ms, "_level", lambda src, dest, **_: dest.write_bytes(src.read_bytes()))
    known = {}
    assert ms._make([piece], tmp_path, known, None, ledger, "creator") == 0
    assert calls == ["bed-a"], "the kept audio was paid for again"
    assert len(ledger.paid) == 1
    assert (tmp_path / "bed-a.m4a").read_bytes() == b"MP3"
    assert "song-1" in known["bed-a.m4a"].source
    assert not (tmp_path / ".bed-a.paid.mp3").exists()
