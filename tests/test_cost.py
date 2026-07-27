import pytest

from pipeline.cost import (
    SpendCapExceededError,
    SpendLedger,
    estimate_tts_usd,
    month_key,
)


def test_estimate_math(settings):
    assert estimate_tts_usd(1000, settings) == settings.usd_per_1k_chars
    assert estimate_tts_usd(784, settings) == pytest.approx(784 / 1000 * settings.usd_per_1k_chars)


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
        ledger.guard_tts_spend(1000)  # ~$0.15 > remaining $0.01
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
