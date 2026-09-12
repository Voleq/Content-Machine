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


def test_a_figure_written_for_the_eye_warns_and_never_blocks():
    """One `$1,234.56` reaching TTS is read wrong, out loud, on a figure the
    on-screen fact-check gate has already verified — two verification systems
    that never meet.

    It is a WARNING because whether the number is RIGHT is `fact_check`'s
    question and it has already been asked. This is only how it is spelled.
    """
    findings = voice_lint("Revenue was $1,234.56, down 59.6% on the year.")
    assert findings, "the figures went through unflagged"
    assert all(f.severity == "warn" for f in findings), \
        "a dollar sign must never stop a render"
    said = " ".join(f.message for f in findings)
    assert "one thousand two hundred and thirty-four dollars and fifty-six cents" in said
    assert "fifty-nine point six percent" in said


def test_a_figure_already_spoken_is_left_alone():
    """A check that fires on good writing gets switched off. The bible's own
    examples are written this way."""
    assert voice_lint(
        "Revenue fell fifty-nine point six percent, to a hundred and sixty-two "
        "million, in 2024, across 8 sites.") == []


def test_the_number_check_is_about_the_spelling_not_the_figure():
    """A bare integer is read the same either way, so flagging every year and
    every count would make the check noise and the noise would get it turned
    off. Only the four things a voice actually gets wrong."""
    assert voice_lint("They opened 8 sites in 2024 and closed 12.") == []
    for eye in ("$40M", "18%", "1,400 stores", "3.2 turns of leverage"):
        assert voice_lint(f"The filing says {eye}."), f"{eye} went unflagged"


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


def test_stale_data_blocks_by_default():
    """B5: the README always listed freshness as a blocking gate."""
    s = Settings(_env_file=None)
    out = check_freshness("2026-06-01", s, today=date(2026, 7, 22))
    assert out and "days old" in out[0].message
    assert out[0].severity == "block"


def test_stale_data_can_be_made_advisory():
    s = Settings(data_stale_blocks=False, _env_file=None)
    out = check_freshness("2026-06-01", s, today=date(2026, 7, 22))
    assert out[0].severity == "warn"


def test_a_missing_as_of_date_blocks_rather_than_skipping():
    """An absent date is the absence of evidence, not evidence."""
    out = check_freshness("", Settings(_env_file=None))
    assert out and out[0].severity == "block"


def test_an_unreadable_as_of_date_blocks_rather_than_skipping():
    out = check_freshness("last tuesday", Settings(_env_file=None))
    assert out and out[0].severity == "block"
    assert "not evidence of freshness" in out[0].message


@pytest.mark.parametrize("written,expected", [
    ("2026-09-03", date(2026, 9, 3)),
    # US format, which is what a US-locale export of US market data writes.
    # Read day-first this was 3 March — six months adrift and inside any
    # staleness limit either way, so the gate said nothing.
    ("09/03/2026", date(2026, 9, 3)),
    ("3-Sep-2026", date(2026, 9, 3)),
    ("3 Sep 2026", date(2026, 9, 3)),
    ("Sep 3, 2026", date(2026, 9, 3)),
    ("September 3, 2026", date(2026, 9, 3)),
    ("2026-09-03 00:00:00", date(2026, 9, 3)),
    # A cell read as a raw Excel serial (days since 1899-12-30).
    ("46268", date(2026, 9, 3)),
])
def test_the_shapes_a_sheet_actually_writes_a_date_in_are_all_read(
        written, expected):
    """Every one of these used to return None and skip the check."""
    from pipeline.gates import _parse_as_of

    assert _parse_as_of(written) == expected


def test_a_stale_us_format_date_is_now_caught():
    """The end-to-end version of the format above: the gate fires."""
    s = Settings(_env_file=None)
    # 9 March, read a US sheet correctly -> 100+ days stale on 20 June.
    out = check_freshness("03/09/2026", s, today=date(2026, 6, 20))
    assert out and out[0].severity == "block"


# ------------------------------------------------ figures that reach the screen


def _long(text, settings):
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(text, "EXMPL", settings)
    return script


def test_a_wrong_figure_blocks_whether_it_is_spoken_or_on_screen(settings, data,
                                                            long_valid_text):
    """The asymmetry is gone: both block now (B4).

    The old reasoning was that a spoken figure is a sentence a viewer hears
    once and a linter can misread, while a figure in a `[PLATE]` slot is
    typed by the director and held on screen for six seconds. The first half
    of that was true of the OLD linter, which skipped every percentage and
    everything under a thousand and compared against a whole series at once.
    A check that crude could not be trusted to stop anything.

    It is not that crude any more, and a wrong number is wrong whichever way
    it reaches the viewer — so the thing the README calls the last line of
    defence is now allowed to be one.
    """
    from pipeline.gates import onscreen_fact_check

    invented = long_valid_text.replace("row-1=400,452,471,491,496,496",
                                       "row-1=400,452,471,491,496,720")
    out = onscreen_fact_check(_long(invented, settings), data)
    assert out and all(f.severity == "block" for f in out)
    assert "720" in out[0].message

    spoken = fact_check("Revenue was seven hundred and twenty million.", data)
    assert spoken and all(f.severity == "block" for f in spoken)


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
    assert "143 plates" in report
    assert "Never reached in a recent render" in report
    # It groups by family, because "eighteen room angles unused" is actionable
    # and a list of 143 keys is not.
    assert "room:" in report or "none" in report


# ------------------------------------------------------------------ suite


def test_run_gates_is_silent_on_a_clean_script(settings, data, long_valid_text):
    """Silence means proceed — that is the whole contract."""
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    # A date the gate would call stale is not a clean script — freshness
    # blocks by default now (B5) — so the fixture's as-of is read as today.
    report = run_gates(script, settings, data=data,
                       as_of=date.today().isoformat(), skeptic=False)
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


# --------------------------------------------------------------------------
# What nothing can reach — a class of defect, not an instance.
# --------------------------------------------------------------------------


def test_the_doctor_reports_what_no_template_can_reach(settings):
    """`room/high-desk-down` sat in the kit with no template naming its role.

    Not an error, not a warning, no failing test: an angle that simply never
    appeared, found by somebody noticing. Noticing is not a method, so the
    doctor walks every shot file, every chapter type and the renderer's own
    literals and says which plates have a route to the screen.
    """
    from pipeline.gates import kit_doctor_text

    text = kit_doctor_text(settings)
    assert "No shot template reaches" in text


def test_a_plate_named_only_through_a_room_role_is_reachable(settings):
    """A template writes `room/talk`, not `room/desk-front-16x9`.

    A walk that only read plate keys would report all nine angles as
    unreachable and bury the one that actually is.
    """
    from pipeline.gates import reachable_plates
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    routes = reachable_plates(reg)
    for key in ("room/desk-front-16x9", "room/low-desk-height-16x9",
                "room/high-desk-down-16x9", "room/desk-front-9x16"):
        assert key in routes["template"], f"{key} has no route through a role"


def test_a_plate_the_renderer_reaches_by_name_is_not_a_gap(settings):
    """The annotations, the media frames and the row band are the renderer's.

    No template mentions them and none should: a director writes `[SCRIBBLE]`,
    not `[PLATE: annotations/strike-out]`, and the row band is named by another
    plate's own slot. Counting those as gaps would bury the real ones under
    twenty entries nobody can act on.
    """
    from pipeline.gates import reachable_plates
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    routes = reachable_plates(reg)
    for key in ("annotations/strike-out", "overlays/row-band",
                "frames/capture-frame-16x9", "frames/media-frame-t1-16x9"):
        assert key in routes["code"], f"{key} reads as unreachable"


def test_a_tag_route_is_not_credited_for_the_set_or_the_host(settings):
    """The chapter curation lists `room/` and `host/` as universal.

    Every chapter has a set and a host — but a director does not write a
    [PLATE] for either, the renderer does. Crediting that curation as a tag
    route made this report say every plate had a way to the screen while
    `room/high-desk-down` demonstrably did not.
    """
    from pipeline.gates import reachable_plates
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    routes = reachable_plates(reg)
    assert not [k for k in routes["tag"]
                if k.split("/", 1)[0] in ("room", "host", "annotations")]


# --------------------------------------------------------------------------
# The gate that makes a production render possible.
# --------------------------------------------------------------------------


def _fake_assets(tmp_path, settings, *, real: bool):
    """An assets tree with only the audio the gate scans, provenance declared.

    `real=True` is what `scripts/fetch_sfx.py` leaves behind: a sidecar saying
    every file came from somewhere with a licence on it.
    """
    import json as _json

    from pipeline.audio_assets import ROOM_TONE_NAME
    from pipeline.models import SFX_KEYS

    sfx = tmp_path / "assets" / "sfx"
    sfx.mkdir(parents=True)
    names = [f"{k}.wav" for k in SFX_KEYS] + [ROOM_TONE_NAME]
    for name in names:
        (sfx / name).write_bytes(b"RIFF....WAVEfmt ")
    if real:
        (sfx / "SOURCES.json").write_text(_json.dumps({"files": {
            n: {"source": f"https://freesound.org/s/{i}/", "licence": "CC0",
                "author": "somebody", "generated": False}
            for i, n in enumerate(names)
        }}), encoding="utf-8")
    return settings.model_copy(update={"assets_dir": tmp_path / "assets"})


def test_the_audio_gate_no_longer_looks_for_a_music_bed(tmp_path, settings):
    """It scanned two directories and one of them held a synthesised bed.

    With the bed deleted, `assets/sfx` is the whole scan — which means the
    effects are the only thing between a placeholder and an upload, and
    `scripts/fetch_sfx.py` is the only thing that clears the gate.
    """
    from pipeline.audio_assets import generated_audio

    placeheld = _fake_assets(tmp_path, settings, real=False)
    reported = generated_audio(placeheld)
    assert reported, "the placeholders still have to be reported"
    assert all(name.startswith("sfx/") for name in reported), \
        f"the gate is scanning somewhere other than sfx/: {reported}"


def test_check_audio_passes_outright_once_the_real_effects_are_fetched(
        tmp_path, settings):
    """THE GATE THAT MAKES A PRODUCTION RENDER POSSIBLE.

    `check_audio` blocks a final render outside MOCK_MODE on any placeholder
    it finds. It used to find the bed no matter what an operator did, because
    nothing was ever going to fetch a licensed one — so a production render
    was blocked forever. With the bed gone, the sound effects are the only
    thing left, and `scripts/fetch_sfx.py` resolves those.
    """
    from pipeline.gates import check_audio

    live = _fake_assets(tmp_path, settings, real=False).model_copy(
        update={"mock_mode": False})
    blocked = check_audio(live, final=True)
    assert [f.severity for f in blocked] == ["block"]
    assert "PLACEHOLDER AUDIO" in blocked[0].message

    fetched = _fake_assets(tmp_path / "fetched", settings, real=True).model_copy(
        update={"mock_mode": False})
    assert check_audio(fetched, final=True) == [], (
        "a final render is still blocked with the bed gone and real effects "
        "fetched — nothing an operator can do would clear this gate")


# --------------------------------------------------------------------------
# B4 — the fact-check's four blind spots. Each of these is a script that the
# old gate read and passed, so each asserts on the FINDINGS, not on which
# branch ran.
# --------------------------------------------------------------------------


def test_a_figure_in_a_millions_sheet_is_checked_not_skipped(settings):
    """The magnitude floor skipped everything under 1,000 — which is most of
    a workbook written in millions."""
    from pipeline.models import CompanyData

    millions = CompanyData(
        history_years=["FY-2", "FY-1", "FY-0"],
        history={"revenue": [452.0, 471.0, 486.0]},
    )
    clean = fact_check("Revenue was four hundred and eighty six million.",
                       millions)
    assert not clean, "486 in a millions sheet IS 486 million"

    wrong = fact_check("Revenue was nine hundred and twelve million.", millions)
    assert wrong, "a figure under 1,000 in the sheet was never checked at all"
    assert wrong[0].severity == "block"


def test_a_wrong_margin_is_caught(settings, data):
    """Every percentage used to be skipped, so no margin was ever checked."""
    assert not fact_check("Gross margin is fifty eight percent.", data)
    out = fact_check("Gross margin is eighty one percent.", data)
    assert out and "gross_margin" in out[0].message


def test_a_wrong_growth_rate_is_caught(settings, data):
    """A percentage against a currency metric is a growth claim."""
    # FY-1 491 -> FY-0 496 is +1.0%; FY-4 400 -> LTM 496 is +24%.
    assert not fact_check("Revenue grew one percent.", data)
    out = fact_check("Revenue grew forty percent.", data)
    assert out and "revenue growth" in out[0].message


def test_a_real_figure_under_the_wrong_year_is_caught_in_speech(settings, data):
    """`_matches` compared against every value at once, so a figure from the
    wrong column passed."""
    assert not fact_check("In FY-2, revenue was four hundred and "
                          "seventy one million.", data)
    out = fact_check("In FY-2, revenue was four hundred million.", data)
    assert out and "FY-2" in out[0].message, \
        "400 is in the series, but it is FY-4's"


def test_a_derived_change_is_a_true_claim(settings, data):
    """491 to 496 is five million of revenue, and the gate has to know it —
    a blocking gate that cannot see a derived claim blocks correct scripts."""
    assert not fact_check("They added five million of revenue.", data)


def test_a_number_attached_to_another_subject_is_not_a_revenue_claim(
        settings, data):
    """"Two hundred and twelve million ON SALES AND MARKETING" is not a
    revenue figure, even in a sentence that later names revenue."""
    assert not fact_check(
        "Two hundred and twelve million on sales and marketing, to add "
        "five million of revenue.", data)


def test_a_spoken_series_recital_is_checked_through_to_the_end(settings, data):
    """One metric, a run of numbers: all of them are claims about it."""
    ok = ("Net income, from the actual filing: minus eight, minus twenty "
          "five, minus forty nine, minus seventy, minus eighty nine.")
    assert not fact_check(ok, data)

    wrong = ok.replace("minus eighty nine", "minus one hundred and forty")
    out = fact_check(wrong, data)
    assert out and "one hundred and forty" in out[0].message, \
        "the last figure in a recital is as checkable as the first"


def test_the_gate_can_still_be_asked_for_advisory_findings(settings, data):
    """The severity is a decision, and it is recorded as one rather than
    hard-coded in fourteen places."""
    out = fact_check("Revenue was nine hundred and twelve million.", data,
                     severity="warn")
    assert out and out[0].severity == "warn"


# --------------------------------------------------------------------------
# B3 — the SHORT lane runs the battery. It used to run `build_short_report`
# and nothing else, on the higher-volume format.
# --------------------------------------------------------------------------


def _short_core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def _short_with_data(core, fixtures, ticker="EXMPL"):
    core.start_lane(5150, "short", ticker)
    core.handle_upload(
        5150, "dennis_data.xlsx",
        (fixtures / "company_data" / "dennis_data.xlsx").read_bytes())
    return core


def test_a_short_with_an_invented_figure_is_refused(settings, fixtures_dir,
                                                    short_valid_json):
    """Asserting on the REPORT the operator sees, not on whether a gate
    function was called."""
    import json

    core = _short_with_data(_short_core(settings), fixtures_dir)
    payload = json.loads(short_valid_json)
    payload["audio_script"] = (
        payload["audio_script"]
        + " Revenue was nine hundred and twelve million dollars.")
    reply = core.intake_script(5150, json.dumps(payload))

    assert "fact-check" in reply.text
    assert "nine hundred and twelve million" in reply.text


def test_a_short_that_names_the_data_vendor_is_refused(settings, fixtures_dir,
                                                       short_valid_json):
    """The LONG hard-blocks this because it would be spoken and captioned.
    A SHORT is spoken and captioned too."""
    import json

    core = _short_with_data(_short_core(settings), fixtures_dir)
    payload = json.loads(short_valid_json)
    payload["audio_script"] = (
        "Straight off the Bloomberg terminal. " + payload["audio_script"])

    from pipeline.parser_short import ScriptParseError

    try:
        reply = core.intake_script(5150, json.dumps(payload))
    except ScriptParseError as e:
        assert "bloomberg" in str(e).lower()
        return
    assert "bloomberg" in reply.text.lower() or "vendor" in reply.text.lower()


def test_a_clean_short_still_passes_the_battery(settings, fixtures_dir,
                                                short_valid_json):
    """The gate that blocks a correct script is worse than no gate."""
    core = _short_with_data(_short_core(settings), fixtures_dir)
    reply = core.intake_script(5150, short_valid_json)
    assert "fact-check" not in reply.text
