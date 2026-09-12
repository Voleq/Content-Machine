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


# --------------------------------------------------------------------------
# Which ElevenLabs model gets called, and what it costs
# --------------------------------------------------------------------------
# Set through the environment, because that is how an operator sets it: only
# fields with an explicit `alias=` accept the SCREAMING spelling as a keyword,
# and `extra="ignore"` swallows the rest without a word.


def test_the_model_can_be_named_outright(monkeypatch):
    """ELEVEN_USE_PREMIUM was a boolean over two hardcoded ids, and nothing
    documented a way past it — so eleven_v3, the only model that honours
    [SIGH] instead of reading it aloud, could not be chosen in practice."""
    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_v3")
    assert Settings(_env_file=None).active_eleven_model == "eleven_v3"


def test_the_deprecated_boolean_still_does_what_it_did(monkeypatch):
    """An .env written before ELEVEN_MODEL_ID existed must not change meaning."""
    monkeypatch.setenv("ELEVEN_USE_PREMIUM", "true")
    assert Settings(_env_file=None).active_eleven_model == "eleven_multilingual_v2"

    monkeypatch.delenv("ELEVEN_USE_PREMIUM")
    assert Settings(_env_file=None).active_eleven_model == "eleven_turbo_v2_5"


def test_naming_the_model_beats_the_deprecated_boolean(monkeypatch):
    """One of them has to win, and it is the one that can name any model."""
    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_v3")
    monkeypatch.setenv("ELEVEN_USE_PREMIUM", "true")
    assert Settings(_env_file=None).active_eleven_model == "eleven_v3"


def test_the_audio_tag_path_turns_itself_on_with_the_model(monkeypatch):
    """Selecting v3 has to be enough. expand_delivery degrades [SIGH] to a
    break on anything else — correctly, since an unsupported tag is read
    aloud — so the model setting is the only switch there should be."""
    from pipeline.models import TagType
    from pipeline.tts import expand_delivery

    class _Ev:
        type = TagType.SIGH
        char_offset = 5

    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_v3")
    text, _, _ = expand_delivery("Well. Fine.", [_Ev()],
                              Settings(_env_file=None).active_eleven_model)
    assert "[sighs]" in text

    monkeypatch.delenv("ELEVEN_MODEL_ID")
    text, _, _ = expand_delivery("Well. Fine.", [_Ev()],
                              Settings(_env_file=None).active_eleven_model)
    assert "[sighs]" not in text and "<break" in text


def test_the_tts_rate_follows_the_model(monkeypatch):
    """The rate is metered against by SpendLedger, not merely displayed: at a
    flat 0.15 a $50 cap stopped paid calls after about $16.67 of real spend."""
    assert Settings(_env_file=None).tts_usd_per_1k_chars == 0.05

    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_multilingual_v2")
    assert Settings(_env_file=None).tts_usd_per_1k_chars == 0.10

    # v3 is TWICE turbo, and the audio tags are what the difference buys.
    # `eleven_v3_conversational` is the $0.05 one and is a different model.
    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_v3")
    assert Settings(_env_file=None).tts_usd_per_1k_chars == 0.10

    monkeypatch.setenv("ELEVEN_MODEL_ID", "eleven_v3_conversational")
    assert Settings(_env_file=None).tts_usd_per_1k_chars == 0.05


def test_the_shipped_dotenv_example_actually_loads():
    """`bootstrap.sh` copies `.env.example` to `.env` verbatim on a clean
    install, so anything in it that pydantic rejects is a bot that will not
    start on a box where everything else went right.

    The case that motivated this: `USD_PER_1K_CHARS=` — a key deliberately
    shipped blank so the rate follows the model — arrives as the empty string,
    which float validation refuses.
    """
    example = Path(__file__).resolve().parents[1] / ".env.example"
    s = Settings(_env_file=example)
    from config import ELEVEN_USD_PER_1K_CHARS

    assert s.mock_mode is True, "the shipped example must not start live"
    # Read off the table rather than a list here: an example that names a model
    # the pricing table does not know would raise at the first cost estimate.
    assert s.active_eleven_model in ELEVEN_USD_PER_1K_CHARS
    assert s.tts_usd_per_1k_chars > 0


def _example_keys() -> set[str]:
    """Every `NAME=` in `.env.example`, commented-out ones included.

    A commented line still documents the setting — `# CACHE_DIR=` tells you
    the knob exists and that blank is the default — which is the whole job
    of this file.
    """
    import re

    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", text, re.M))


def test_every_setting_is_discoverable_in_the_dotenv_example():
    """`.env.example` is the ONLY discovery surface a setting has (P2).

    Seventeen aliases had none. `OLLAMA_NUM_CTX` is the sharpest: unset, it
    silently truncates every filing brief — the exact defect it was added to
    fix — and an operator who never learns it exists gets confident briefs
    built from half a section. `PUBLISH_HOUR` and `PUBLISH_TIMEZONE` are the
    next worst: they decide when a video goes public, and inheriting them is
    not the same as choosing them.

    This is the cheap permanent close. A setting added without a line here
    fails on the commit that adds it, which is the only moment the author
    still knows what to write.
    """
    aliases = {f.alias for f in Settings.model_fields.values() if f.alias}
    missing = sorted(aliases - _example_keys())
    assert not missing, (
        f"{len(missing)} setting(s) exist in Settings and are documented "
        f"nowhere an operator will look:\n  " + "\n  ".join(missing)
        + "\n\nAdd each to .env.example with its default and a one-line "
          "comment saying what goes wrong when it is left alone.")


def test_the_dotenv_example_does_not_document_settings_that_are_gone():
    """The same lie in the other direction, and the one Group L would have
    left behind: eleven `EXCEL_*` keys describing a subsystem that had been
    deleted. A name here that resolves to nothing is an operator setting a
    value and waiting for an effect that cannot arrive.
    """
    fields = Settings.model_fields
    known = {f.alias for f in fields.values() if f.alias}
    # Fields with no explicit alias are still settable by their own name,
    # case-insensitively — that is pydantic-settings' default.
    known |= {name.upper() for name in fields}
    stale = sorted(_example_keys() - known)
    assert not stale, (
        "documented in .env.example and read by nothing:\n  "
        + "\n  ".join(stale))


# --------------------------------------------------------------- the mix
# One setting the operator tunes by listening, so it has to survive being typed
# by hand into a .env. The chapter-silence list was the other one, and it went
# with the bed it muted: with nothing to mute, a setting that does nothing is
# worse than no setting.


def test_the_chapter_cue_is_a_key_or_nothing():
    """Unknown keys are the renderer's problem, not startup's — same contract
    as `[SOUND: …]`, which warns and skips rather than stopping a render."""
    assert Settings(_env_file=None).chapter_cue_sfx == "keyboard_clack"
    assert Settings(CHAPTER_CUE_SFX="", _env_file=None).chapter_cue_sfx == ""
    assert Settings(CHAPTER_CUE_SFX="airhorn", _env_file=None).chapter_cue_sfx == "airhorn"
