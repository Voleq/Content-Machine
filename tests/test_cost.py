import pytest

from pipeline.cost import (
    SpendCapExceededError,
    SpendLedger,
    estimate_tts_usd,
    month_key,
)


def test_estimate_math(settings):
    rate = settings.tts_usd_per_1k_chars
    assert estimate_tts_usd(1000, settings) == rate
    assert estimate_tts_usd(784, settings) == pytest.approx(784 / 1000 * rate)


def test_the_rate_is_the_selected_model_s_rate(settings):
    """A hardcoded rate cannot be true of two models at two prices.

    It was 0.15, and turbo bills at 0.05 - so the ledger below metered a $50
    cap down to about $16.67 of real spend, and every cost report the operator
    approved against read three times high.
    """
    from config import ELEVEN_USD_PER_1K_CHARS

    turbo = settings.model_copy(update={"eleven_model_id": "eleven_turbo_v2_5"})
    assert estimate_tts_usd(1000, turbo) == ELEVEN_USD_PER_1K_CHARS["eleven_turbo_v2_5"]

    premium = settings.model_copy(
        update={"eleven_model_id": "eleven_multilingual_v2"})
    assert estimate_tts_usd(1000, premium) == ELEVEN_USD_PER_1K_CHARS["eleven_multilingual_v2"]
    assert estimate_tts_usd(1000, premium) > estimate_tts_usd(1000, turbo)


def test_an_unknown_model_bills_at_the_dearest_known_rate(settings):
    """Guessing low overspends a cap the operator set so it could not be."""
    from config import ELEVEN_USD_PER_1K_CHARS

    unknown = settings.model_copy(update={"eleven_model_id": "eleven_not_yet"})
    assert unknown.tts_usd_per_1k_chars == max(ELEVEN_USD_PER_1K_CHARS.values())


def test_usd_per_1k_chars_still_overrides_everything(settings):
    """Prices move; the escape hatch has to keep working."""
    pinned = settings.model_copy(update={"usd_per_1k_chars": 0.42})
    assert estimate_tts_usd(1000, pinned) == 0.42


def test_ledger_persists_across_instances(settings):
    ledger = SpendLedger(settings)
    assert ledger.mtd_spend_usd() == 0.0
    ledger.record_tts(1.25)
    ledger.record_tts(0.50)

    fresh = SpendLedger(settings)
    assert fresh.mtd_spend_usd() == pytest.approx(1.75)
    assert month_key() in fresh._load()


def test_guard_blocks_over_cap(settings):
    tight = settings.model_copy(update={"monthly_spend_cap_usd": 0.10})
    ledger = SpendLedger(tight)
    ledger.record_tts(0.09)
    with pytest.raises(SpendCapExceededError, match="monthly"):
        ledger.guard_tts_spend(1000)  # ~$0.05 at turbo > remaining $0.01
    # a tiny job that fits still passes
    assert ledger.guard_tts_spend(50) > 0


def test_pexels_counter_and_cap(settings):
    tight = settings.model_copy(update={"pexels_monthly_call_cap": 2})
    ledger = SpendLedger(tight)
    ledger.check_pexels_budget()
    ledger.record_pexels_call()
    ledger.record_pexels_call()
    assert ledger.pexels_calls_this_month() == 2
    with pytest.raises(SpendCapExceededError, match="Pexels"):
        ledger.check_pexels_budget()


def test_corrupt_state_file_recovers(settings):
    ledger = SpendLedger(settings)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text("{corrupt", encoding="utf-8")
    assert ledger.mtd_spend_usd() == 0.0
    ledger.record_tts(1.0)
    assert ledger.mtd_spend_usd() == 1.0


def test_the_short_report_blocks_on_placeholder_audio(settings, short_valid_json):
    """The operator sees it before tapping Approve, not after the upload.

    The SHORT lane has no gate battery — the LONG runs `run_gates` at intake
    and folds its findings into the same report — so the daily-volume format
    was the one with nothing between a synthesised cash register and YouTube.
    """
    from pipeline.cost import build_short_report
    from pipeline.parser_short import parse_short_script
    from pipeline.tts import TTSEngine

    live = settings.model_copy(update={"mock_mode": False})
    script, warnings = parse_short_script(short_valid_json, live)
    report = build_short_report(script, warnings, live, SpendLedger(live),
                                TTSEngine(live))
    blockers = [b for b in report.blocking if "PLACEHOLDER AUDIO" in b]
    assert blockers, f"nothing blocked on the placeholders: {report.blocking}"
    assert "scripts/fetch_sfx.py" in blockers[0]
    assert not report.approvable, "a blocked report must not be approvable"
    assert "PLACEHOLDER AUDIO" in report.render_text()

    # In MOCK_MODE the same files are a warning: the offline suite and every
    # draft run on them, and a gate that stopped those teaches gate-skipping.
    draft_report = build_short_report(script, warnings, settings,
                                      SpendLedger(settings), TTSEngine(settings))
    assert draft_report.approvable
    assert any("PLACEHOLDER AUDIO" in w for w in draft_report.warnings)


# --------------------------------------------------------------------------
# Reach on the approval report.
# --------------------------------------------------------------------------


def test_the_short_report_states_what_the_script_reaches(settings, short_valid_json):
    """`kit_assets_used` has been in the render manifest since the kit existed
    and nobody ever opened it, so a short reaching 17 of 442 assets and one
    data plate went unremarked for months. The approval screen is the
    last moment the script can be sent back, so it says so there."""
    import re

    from pipeline.cost import build_short_report
    from pipeline.parser_short import parse_short_script
    from pipeline.tts import TTSEngine

    from pipeline.plates import load_plates

    script, warnings = parse_short_script(short_valid_json, settings)
    report = build_short_report(script, warnings, settings,
                                SpendLedger(settings), TTSEngine(settings))
    line = next(ln for ln in report.render_text().splitlines()
                if ln.startswith("Kit: "))
    assert re.fullmatch(
        r"Kit: \d+ of \d+ plates · \d+ families · \d+ data plates?",
        line), line
    # the denominator is the library, read live — the point of the line is that
    # the numerator is small against it
    assert "of 143 plates" in line


def test_the_line_counts_what_the_script_actually_names(settings, short_valid_json):
    import json

    from pipeline.cost import build_short_report
    from pipeline.parser_short import parse_short_script
    from pipeline.tts import TTSEngine

    import re

    data = json.loads(short_valid_json)
    # stripped back to two named beats, so the count is checkable by hand
    data["audio_script"] = ("[PROP: crushed-flat = -$89M] [PROP: c-doc-tear] "
                            + re.sub(r"\[PROP:[^\]]*\]\s*", "",
                                     data["audio_script"]))
    script, warnings = parse_short_script(json.dumps(data), settings)
    report = build_short_report(script, warnings, settings,
                                SpendLedger(settings), TTSEngine(settings))
    assert "plates ·" in report.kit_reach and "data plate" in report.kit_reach


def test_the_long_report_carries_the_same_line(settings, long_valid_text, workspace):
    """One shape, both formats: an operator reads the same number in both
    lanes rather than learning two reports."""
    from pipeline.cost import build_long_report
    from pipeline.parser_long import parse_long_script
    from pipeline.tts import TTSEngine

    script, warnings = parse_long_script(long_valid_text, "EXMPL", settings)
    report = build_long_report(script, warnings, [], [], settings,
                               SpendLedger(settings), TTSEngine(settings), [], 0)
    from pipeline.plates import load_plates

    assert report.kit_reach.startswith("Kit: ")
    assert "of 143 plates" in report.kit_reach
    assert report.kit_reach in report.render_text()


def test_a_blank_rate_in_a_dotenv_is_not_a_crash(tmp_path):
    """.env.example ships USD_PER_1K_CHARS blank, and bootstrap.sh copies it.

    A blank key arrives as the empty string; float validation rejects it. An
    operator clearing a rate they no longer want to pin would have got a
    pydantic traceback at startup in answer to asking for the default.
    """
    from config import Settings

    env = tmp_path / ".env"
    env.write_text("USD_PER_1K_CHARS=\nELEVEN_MODEL_ID=\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.usd_per_1k_chars is None
    assert s.active_eleven_model == "eleven_turbo_v2_5"
    assert s.tts_usd_per_1k_chars == 0.05
