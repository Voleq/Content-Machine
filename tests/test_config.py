from pathlib import Path

import pytest

from config import Settings, detect_ffmpeg


def test_mock_mode_default_true(tmp_path: Path):
    s = Settings(_env_file=None)
    assert s.mock_mode is True, "MOCK_MODE must default to on — hard cost rule"


def test_budgets_defaults():
    s = Settings(_env_file=None)
    assert s.short_max_chars == 800
    assert s.long_max_chars == 36000  # complexity-driven ceiling (~40 min)
    assert s.monthly_spend_cap_usd == 50.0
    assert s.max_chars("short") == 800
    assert s.max_chars("long") == 36000


def test_operator_ids_csv_parsing():
    s = Settings(OPERATOR_CHAT_IDS="123, 456", _env_file=None)
    assert s.operator_chat_ids == [123, 456]


def test_voice_settings_per_format():
    s = Settings(_env_file=None)
    short = s.voice_settings("short")
    long_ = s.voice_settings("long")
    assert short["stability"] < long_["stability"], "LONG must be the deadpan (stable) voice"
    assert long_["style"] <= 0.1


def test_delivery_backend_validated():
    with pytest.raises(Exception):
        Settings(DELIVERY_BACKEND="ftp", _env_file=None)
    assert Settings(DELIVERY_BACKEND="local", _env_file=None).delivery_backend == "local"


def test_detect_ffmpeg_present():
    ffmpeg, ffprobe = detect_ffmpeg()
    assert ffmpeg and ffprobe
