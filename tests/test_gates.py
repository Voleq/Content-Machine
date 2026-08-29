"""Automated gates — the bot checking its own work before it spends."""

from __future__ import annotations

import pathlib
from datetime import date

import pytest

from config import Settings
from pipeline.company_data import load_company_data
from pipeline.gates import (
    check_freshness,
    extract_numbers,
    fact_check,
    kit_doctor,
    run_gates,
    voice_lint,
)

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def data():
    return load_company_data(FIX / "company_data")


# ---------------------------------------------------------- spoken numbers


@pytest.mark.parametrize("text,expected", [
    ("four hundred million", 400_000_000),
    ("one point four billion", 1_400_000_000),
    ("twenty five thousand", 25_000),
    ("four ninety six", 496),
    ("sixty", 60),
    ("$496M", 496_000_000),
    ("1.2B", 1_200_000_000),
])
def test_spoken_and_written_numbers_parse(text, expected):
    got = extract_numbers(text)
    assert got, f"nothing parsed from {text!r}"
    assert any(abs(n.value - expected) < 1 for n in got), \
        f"{text!r} -> {[n.value for n in got]}, wanted {expected}"


def test_percentages_are_marked():
    nums = extract_numbers("Share count grows six percent a year.")
    assert nums and nums[0].is_percent


def test_prose_without_numbers_yields_nothing():
    assert extract_numbers("The business went sideways.") == []


# ----------------------------------------------------------- fact-checking


def test_a_correct_claim_passes_clean(data):
    ok = "Revenue went four hundred million to four ninety six in five years."
    assert fact_check(ok, data) == []


def test_an_invented_figure_is_caught(data):
    bad = "Revenue went from four hundred million to seven hundred twenty million."
    findings = fact_check(bad, data)
    assert findings, "a figure absent from the data must be flagged"
    assert findings[0].gate == "fact-check"
    assert "revenue" in findings[0].message


def test_the_finding_carries_a_line_reference(data):
    text = "\n".join([
        "An opening line with no numbers at all.",
        "",
        "Revenue was nine hundred million last year.",
    ])
    findings = fact_check(text, data)
    assert findings and findings[0].line == 3
    assert "nine hundred million" in findings[0].excerpt.lower()


def test_rounding_is_tolerated(data):
    """A script says 'four hundred million', the sheet says 400,000,000 —
    and would still pass at 399.5M."""
    assert fact_check("Revenue started at four hundred million.", data) == []


def test_numbers_not_attached_to_a_metric_are_left_alone(data):
    """Free-floating figures are prose. Flagging them would bury the real
    mismatches, and a noisy gate gets ignored."""
    assert fact_check("About four thousand depots, give or take.", data) == []


def test_no_data_means_no_findings():
    assert fact_check("Revenue was nine hundred million.", None) == []


# ------------------------------------------------------------ voice linter


def test_voice_linter_flags_bible_violations():
    findings = voice_lint("This is an insane move!")
    kinds = " ".join(f.message for f in findings)
    assert "hype adjective" in kinds
    assert "exclamation" in kinds


def test_a_vendor_name_blocks():
    findings = voice_lint("According to Refinitiv, revenue fell.")
    assert any(f.severity == "block" for f in findings)


def test_the_linter_never_counts_jokes():
    """Density is the writer's call. A linter policing it would flatten the
    voice, which is the opposite of what the bible asks for."""
    joke_heavy = "\n".join([
        "A plateau in a nice outfit.",
        "They print stock like it's a personality trait.",
        "A vibe with a logo.",
    ])
    assert voice_lint(joke_heavy) == []
    assert voice_lint("Revenue rose. Costs rose more. That is the whole story.") == []


# --------------------------------------------------------------- freshness


def test_fresh_data_passes():
    s = Settings(_env_file=None)
    assert check_freshness("2026-07-20", s, today=date(2026, 7, 22)) == []


def test_stale_data_warns():
    s = Settings(_env_file=None)
    out = check_freshness("2026-06-01", s, today=date(2026, 7, 22))
    assert out and "days old" in out[0].message
    assert out[0].severity == "warn"


def test_stale_data_can_be_made_blocking():
    s = Settings(data_stale_blocks=True, _env_file=None)
    out = check_freshness("2026-06-01", s, today=date(2026, 7, 22))
    assert out[0].severity == "block"


def test_a_missing_as_of_date_is_flagged():
    assert check_freshness("", Settings(_env_file=None))


# ------------------------------------------------------------- kit doctor


def test_the_kit_doctor_runs_without_a_script(settings):
    """The library half — what has been drawn and never reached — is what an
    operator goes looking for, and it needs no script."""
    from pipeline.gates import kit_doctor_text

    report = kit_doctor_text(settings)
    assert "KIT DOCTOR" in report
    assert "113 plates" in report
    assert "Never reached in a recent render" in report
    # It groups by family, because "eighteen room angles unused" is actionable
    # and a list of 113 keys is not.
    assert "room:" in report or "none" in report


# ------------------------------------------------------------------ suite


def test_run_gates_is_silent_on_a_clean_script(settings, data, long_valid_text):
    """Silence means proceed — that is the whole contract."""
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    report = run_gates(script, settings, data=data,
                       as_of="2026-07-01", skeptic=False)
    blocking = [f for f in report.findings if f.severity == "block"]
    assert not blocking, report.text()


def test_the_skeptic_never_runs_offline(settings, long_valid_text):
    """MOCK_MODE must not reach the network, so the pass simply does not run."""
    from pipeline.gates import skeptic_notes

    assert settings.mock_mode
    assert skeptic_notes("anything at all", settings) == []


def test_the_battery_carries_the_audio_gate(settings, data, long_valid_text):
    """`run_gates` is where the LONG's report gets its findings from.

    The banner at the top of a render was the entire defence against
    publishing oscillators. This is the same check, in the shape the operator's
    report already renders — and blocking, on the one combination that would
    reach an upload.
    """
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    offline = run_gates(script, settings, data=data, as_of="2026-07-01",
                        skeptic=False)
    audio = [f for f in offline.findings if f.gate == "audio"]
    assert audio and audio[0].severity == "warn", \
        "MOCK_MODE must warn, never block — the offline suite runs on these"

    live = settings.model_copy(update={"mock_mode": False})
    final = run_gates(script, live, data=data, as_of="2026-07-01", skeptic=False)
    assert [f.severity for f in final.findings if f.gate == "audio"] == ["block"]
    assert any("PLACEHOLDER AUDIO" in f.message for f in final.blocking)
    draft = run_gates(script, live, data=data, as_of="2026-07-01",
                      skeptic=False, final=False)
    assert [f.severity for f in draft.findings if f.gate == "audio"] == ["warn"]


def test_the_doctor_names_the_gap_list_the_next_batch_is_drawn_from(settings):
    """Three questions: what was asked for and missing, what was left empty,
    and what has been drawn and never reached."""
    from pipeline.gates import kit_doctor_text

    text = kit_doctor_text(settings)
    assert "Unresolved plate names" in text
    assert "Slots a script left unfilled" in text
    assert "Never reached in a recent render" in text


def test_an_unknown_plate_blocks_and_is_named(settings):
    from pipeline.gates import kit_doctor
    from pipeline.models import TagEvent, TagType

    class _S:
        events = [TagEvent(type=TagType.PLATE, payload="tables/not-a-plate",
                           char_offset=0, raw_offset=0)]

    findings, stats = kit_doctor(_S(), settings)
    assert stats["unresolved_keys"] == ["[PLATE: not-a-plate]"]
    assert any(f.severity == "block" for f in findings)
