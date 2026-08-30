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


def test_a_construction_used_twice_is_flagged_on_the_second():
    """"One reframe, one simile chain, one bathos drop, one fake-out. Maximum."

    The first use is the licence and the second is the finding — the bible's
    own account of the failure is that no individual one was bad and the
    fourth was tired. So the message carries the line of the first, because a
    writer cannot fix a repeat they cannot see the original of.
    """
    once = "That's not capital return, it's topping up the bath with the plug out."
    assert voice_lint(once) == []

    twice = once + "\nAnd that is not a business, it's a subscription to being poorer."
    out = voice_lint(twice)
    assert len(out) == 1 and out[0].line == 2
    assert "one reframe per script" in out[0].message
    assert "line 1" in out[0].message
    assert out[0].severity == "warn"


def test_the_fake_out_is_recognised_through_its_beat():
    """Its shape is a concession, a beat, then one short clause.

    Which means it cannot be found in `script.narration` at all — the
    tokenizer takes every bracket out of what the voice reads, `[BEAT]`
    included. `delivery_text` is what puts the pacing marks back.
    """
    one = "That defence is real. [BEAT] It's also been four years."
    assert voice_lint(one) == []
    out = voice_lint(one + "\nThe bull case holds. [BEAT] It has also been four years.")
    assert len(out) == 1 and "fake-out" in out[0].message


def test_bathos_is_not_matched_and_that_is_deliberate():
    """The one construction of the four with no surface form.

    A grand setup deflated by something mundane has no lexical marker, and an
    approximation of it would fire on ordinary sentences — which is how a
    check gets switched off, taking the three accurate ones with it.
    """
    from pipeline.gates import _CONSTRUCTIONS

    assert {name for name, _, _ in _CONSTRUCTIONS} == {"reframe", "simile",
                                                       "fake-out"}
    bathos = ("The whole thesis rests on a refinancing in March. There is a "
              "calendar reminder for it. The reminder says lol.\n"
              "Everything depends on the covenant test in the fourth quarter. "
              "There is a second reminder. It says the same thing.")
    assert voice_lint(bathos) == []


def test_twenty_seconds_without_a_turn_is_flagged():
    """The retention rule, in the only unit a writer can act on: seconds."""
    straight = (
        "The company operates a network of regional distribution depots across "
        "eleven states and licenses dispatch software to the operators who run "
        "them, charging per seat per month on annual contracts that renew in the "
        "first quarter and carry a three percent uplift built into the renewal "
        "schedule, which the filing describes at length in a section on revenue "
        "recognition that also covers the treatment of implementation fees and "
        "the amortisation of contract acquisition costs over an estimated "
        "customer life of four years and a bit.")
    out = voice_lint(straight)
    assert len(out) == 1 and "no turn in it" in out[0].message
    assert out[0].severity == "warn"

    # A turn EARLY in a long sentence ends the run there rather than at the
    # full stop. Counting by sentence would charge the forty words after "you"
    # to the stretch before it and report a stretch nobody spoke: here the run
    # that remains is the one AFTER the turn, and it is shorter.
    turned = straight.replace("charging per seat per month",
                              "you pay per seat per month")
    after = voice_lint(turned)
    assert len(after) == 1
    assert after[0].excerpt.startswith("pay per seat")
    assert float(after[0].message.split("about ")[1].split(" ")[0]) < \
        float(out[0].message.split("about ")[1].split(" ")[0])

    # Turns in both halves, and there is nothing to report.
    broken = turned.replace("which the filing describes",
                            "and I will spare you the rest, which the filing describes")
    assert voice_lint(broken) == [], [f.message for f in voice_lint(broken)]


def test_the_committed_long_fixture_passes_the_v2_linter(settings, long_valid_text):
    """A check that fires on good writing gets switched off. This is the proof.

    Both new rules are structural, which is exactly the kind that cries wolf,
    so they are run against the script the repo holds up as the register done
    properly.
    """
    from pipeline.gates import delivery_text
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    text = delivery_text(script)
    assert "[BEAT]" in text, "the pacing marks did not survive into the lint"
    assert voice_lint(text) == [], [f.message for f in voice_lint(text)]


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


# ------------------------------------------------ figures that reach the screen


def _long(text, settings):
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(text, "EXMPL", settings)
    return script


def test_a_figure_on_screen_blocks_where_a_spoken_one_warns(settings, data,
                                                            long_valid_text):
    """The asymmetry is the point, not an inconsistency.

    A spoken figure is a sentence a viewer hears once and a linter can misread.
    A figure in a `[PLATE]` slot is a number the director typed, held on screen
    for six seconds, and screenshotted by anyone who disagrees with it. The
    voice gets to be as confident as v2 asks precisely because these were
    verified before anything rendered.
    """
    from pipeline.gates import onscreen_fact_check

    invented = long_valid_text.replace("row-1=400,452,471,491,496,496",
                                       "row-1=400,452,471,491,496,720")
    out = onscreen_fact_check(_long(invented, settings), data)
    assert out and all(f.severity == "block" for f in out)
    assert "720" in out[0].message

    spoken = fact_check("Revenue was seven hundred and twenty million.", data)
    assert spoken and all(f.severity == "warn" for f in spoken)


def test_a_real_figure_under_the_wrong_year_is_caught(settings, data,
                                                      long_valid_text):
    """The failure a membership test cannot see.

    Every number here is in the series — two of them are just in each other's
    columns, which is a table that lies about which year each figure belongs
    to. Six cells under six period heads against a six-period history is a
    column-by-column comparison or it is nothing.
    """
    from pipeline.gates import onscreen_fact_check

    swapped = long_valid_text.replace("row-1=400,452,471,491,496,496",
                                      "row-1=452,400,471,491,496,496")
    out = onscreen_fact_check(_long(swapped, settings), data)
    assert len(out) == 2
    assert "in that column" in out[0].message


def test_the_committed_fixture_agrees_with_its_own_data(settings, data,
                                                        long_valid_text):
    """Every on-screen figure in the exemplary script, against the sheet.

    It did not, when this gate was written: the four-row sheet, the row
    spotlight, the unit ladder and the cash-flow statement all carried figures
    nobody had reconciled against `fixtures/company_data`, and the video
    rendered clean for as long as nothing checked.
    """
    from pipeline.gates import onscreen_fact_check

    out = onscreen_fact_check(_long(long_valid_text, settings), data)
    assert out == [], [f"{f.excerpt} -> {f.message}" for f in out]


def test_a_negative_cell_is_read_as_negative(settings, data):
    """`extract_numbers` is built for prose and returns the magnitude.

    It reads "-8" as eight, so a loss compared clean against a profit and
    every negative row on every sheet went through. A cell is not a sentence.
    """
    from pipeline.gates import _cell_value

    assert _cell_value("-8") == -8.0
    assert _cell_value("(8)") == -8.0          # accountants' parentheses
    assert _cell_value("-1.4B") == -1.4e9
    assert _cell_value("") is None             # an empty cell means NO DATA
    assert _cell_value("n/a") is None


def test_the_unit_is_read_from_the_kicker_as_well_as_the_slot(settings):
    """`row-spotlight` carries it as "NET INCOME, $M"; the sheet has a slot.

    Reading only `unit` compared millions against dollars on every spotlight
    in the library, and blocked every correct one.
    """
    from pipeline.gates import _declared_unit

    assert _declared_unit({"unit": "$M"}) == 1e6
    assert _declared_unit({"kicker": "NET INCOME, $M"}) == 1e6
    assert _declared_unit({"kicker": "FROM THE HIGH"}) is None


def test_cash_the_balance_is_not_matched_by_cash_the_flow(settings, data):
    """A blocking gate must never block a correct sheet.

    The bare word "cash" is inside "free cash flow", "cash from operations",
    "cash used investing" and "net change in cash". Matching a flow against a
    balance would fail every cash-flow statement in the library.
    """
    from pipeline.gates import _METRIC_WORDS

    assert "cash" not in _METRIC_WORDS["cash"]
    assert all("cash" != w for w in _METRIC_WORDS["cash"])


# ------------------------------------------------------------- kit doctor


def test_the_kit_doctor_runs_without_a_script(settings):
    """The library half — what has been drawn and never reached — is what an
    operator goes looking for, and it needs no script."""
    from pipeline.gates import kit_doctor_text

    report = kit_doctor_text(settings)
    assert "KIT DOCTOR" in report
    assert "140 plates" in report
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
