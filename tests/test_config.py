from pathlib import Path

import pytest

from config import Settings, detect_ffmpeg


def test_mock_mode_default_true(tmp_path: Path):
    s = Settings(_env_file=None)
    assert s.mock_mode is True, "MOCK_MODE must default to on — hard cost rule"


def test_budgets_defaults():
    s = Settings(_env_file=None)
    assert s.short_max_chars == 1400  # 60–75s retention-first short
    assert s.long_max_chars == 36000  # complexity-driven ceiling (~40 min)
    assert s.monthly_spend_cap_usd == 50.0
    assert s.max_chars("short") == 1400
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


# --------------------------------------------------------------------------
# WSL: the runtime dirs must be on the Linux filesystem
# --------------------------------------------------------------------------
# Under WSL2, /mnt/<letter> is a Windows drive reached through the 9p/drvfs
# translation layer. cache/segments is thousands of small files that get
# stat'd on every render to decide what to reuse — precisely the access
# pattern that layer is worst at, and precisely the operation that is supposed
# to make a re-render cheap. Warn at startup rather than let it be discovered
# as "renders got slow for no reason".


def test_the_runtime_dirs_default_to_the_linux_filesystem():
    s = Settings(_env_file=None)
    assert s.windows_drive_dirs() == []
    for attr in Settings.RUNTIME_DIR_ATTRS:
        assert not str(getattr(s, attr)).startswith("/mnt/")


def test_a_runtime_dir_on_a_windows_drive_is_reported():
    s = Settings(_env_file=None,
                 workspace_dir=Path("/mnt/c/Users/op/workspace"),
                 cache_dir=Path("/mnt/d/cache"),
                 state_dir=Path("/home/op/state"))
    assert [attr for attr, _ in s.windows_drive_dirs()] == ["workspace_dir", "cache_dir"]


def test_the_warning_names_the_setting_and_the_fix(caplog):
    s = Settings(_env_file=None, cache_dir=Path("/mnt/c/dennis/cache"))
    import logging as _logging

    log = _logging.getLogger("test_windows_drive")
    with caplog.at_level(_logging.WARNING, logger="test_windows_drive"):
        offenders = s.warn_about_windows_drives(log)

    assert offenders == ["cache_dir"]
    message = caplog.text
    assert "/mnt/c/dennis/cache" in message
    assert "CACHE_DIR" in message, "name the env var the operator has to set"
    assert "Linux filesystem" in message


def test_a_symlink_into_a_windows_drive_is_caught_too(tmp_path):
    """Prefix-matching the configured string would miss this, and a symlink
    into /mnt/c is the realistic way it happens by accident."""
    target = Path("/mnt/c/dennis-cache")
    link = tmp_path / "cache"
    link.symlink_to(target)
    s = Settings(_env_file=None, cache_dir=link)
    assert [attr for attr, _ in s.windows_drive_dirs()] == ["cache_dir"]


def test_mnt_itself_counts_but_a_lookalike_does_not():
    on = Settings(_env_file=None, state_dir=Path("/mnt"))
    assert [a for a, _ in on.windows_drive_dirs()] == ["state_dir"]
    # /mnturbo is not under /mnt — a plain string prefix test would say it is
    off = Settings(_env_file=None, state_dir=Path("/mnturbo/state"))
    assert off.windows_drive_dirs() == []
