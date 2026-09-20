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
    approved against read three times high. That erred safe. The correction
    that replaced it did not: see the exactness tests below.
    """
    from config import ELEVEN_USD_PER_1K_CHARS

    turbo = settings.model_copy(update={"eleven_model_id": "eleven_turbo_v2_5"})
    assert estimate_tts_usd(1000, turbo) == ELEVEN_USD_PER_1K_CHARS["eleven_turbo_v2_5"]

    premium = settings.model_copy(
        update={"eleven_model_id": "eleven_multilingual_v2"})
    assert estimate_tts_usd(1000, premium) == ELEVEN_USD_PER_1K_CHARS["eleven_multilingual_v2"]
    assert estimate_tts_usd(1000, premium) > estimate_tts_usd(1000, turbo)


def test_an_unknown_model_refuses_to_be_priced(settings):
    """It used to bill at the dearest known rate, on the reasoning that
    guessing high is the safe direction. But a guess is a guess, and the one
    that actually shipped went the other way: v3 priced at v3-conversational's
    $0.05 would have metered a $50 cap through about $100 of real spend.

    A missing entry and a wrong one are indistinguishable at runtime. Only one
    of them can be made to announce itself.
    """
    from config import UnknownModelPriceError

    unknown = settings.model_copy(update={"eleven_model_id": "eleven_not_yet"})
    with pytest.raises(UnknownModelPriceError, match="eleven_not_yet"):
        unknown.tts_usd_per_1k_chars


def test_the_price_lookup_is_exact_and_not_a_prefix(settings):
    """`eleven_v3_conversational` starts with `eleven_v3` and costs HALF as
    much. Any prefix or substring match would price the dearer model at the
    cheaper one's rate — which is the exact failure this table already had.

    `direction.performs_audio_tags` substring-matches and is right to: both
    models perform audio tags. The two questions look alike; the lookups must
    not be shared.
    """
    from config import ELEVEN_USD_PER_1K_CHARS

    v3 = settings.model_copy(update={"eleven_model_id": "eleven_v3"})
    conv = settings.model_copy(
        update={"eleven_model_id": "eleven_v3_conversational"})
    assert v3.tts_usd_per_1k_chars == 0.10
    assert conv.tts_usd_per_1k_chars == 0.05
    assert v3.tts_usd_per_1k_chars == 2 * conv.tts_usd_per_1k_chars
    assert ELEVEN_USD_PER_1K_CHARS["eleven_v3"] > \
        ELEVEN_USD_PER_1K_CHARS["eleven_v3_conversational"]


def test_the_cap_is_never_metered_slower_than_the_real_rate(settings):
    """The direction that matters. Overstating a rate stops paid work early;
    understating it lets the only hard stop in the system wave spend through.
    """
    from config import ELEVEN_USD_PER_1K_CHARS
    from pipeline.cost import SpendCapExceededError, SpendLedger

    live = settings.model_copy(update={"eleven_model_id": "eleven_v3",
                                       "monthly_spend_cap_usd": 1.00})
    assert live.tts_usd_per_1k_chars == ELEVEN_USD_PER_1K_CHARS["eleven_v3"]

    ledger = SpendLedger(live)
    # 10,000 characters of v3 is $1.00 exactly — the cap, not a penny under.
    ledger.record_tts(0.50)
    with pytest.raises(SpendCapExceededError):
        ledger.guard_tts_spend(10_000)


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
    # THE DENOMINATOR IS THE LIBRARY, READ LIVE. Asserted against the
    # registry rather than against a number typed here: the kit grew from
    # 143 plates to 270 in delta-14, and a literal would have made a correct
    # reach line look like a regression on the day the operator ingests it.
    # What the line is for is that the numerator is small against whatever
    # the library currently holds.
    from pipeline.plates import load_plates

    total = len(load_plates(settings.assets_dir).keys())
    assert f"of {total} plates" in line


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
    from pipeline.plates import load_plates

    assert f"of {len(load_plates(settings.assets_dir).keys())} plates" \
        in report.kit_reach
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


def test_the_refusal_reaches_the_approval_screen(settings, short_valid_json):
    """A raise is only worth anything if it is not swallowed on the way out.

    The report path runs through several broad `except Exception` handlers on
    its way to the operator, and the whole point of refusing to guess a rate is
    that the refusal is louder than a wrong number. So this checks the real
    builder, not the property.
    """
    from config import UnknownModelPriceError
    from pipeline.cost import build_short_report
    from pipeline.parser_short import parse_short_script
    from pipeline.tts import TTSEngine

    unpriced = settings.model_copy(
        update={"eleven_model_id": "eleven_v3_preview_2026"})
    script, warnings = parse_short_script(short_valid_json, unpriced)
    with pytest.raises(UnknownModelPriceError, match="eleven_v3_preview_2026"):
        build_short_report(script, warnings, unpriced,
                           SpendLedger(unpriced), TTSEngine(unpriced))


def test_a_clip_that_fell_to_filler_is_named_on_the_approval_report(
        settings, long_valid_text, workspace):
    """A silent miss is the failure that costs the most.

    `[CLIP: lebron three pointer]` was written because the point needed
    SHOWING. When the whole chain misses, the render still succeeds, the
    generic card is still drawn, and the only trace was `pexels: no results`
    in a log nobody reads — so the beat is dead and the operator approves it
    anyway. The report is the last screen before the money.
    """
    from pipeline.broll import Visual
    from pipeline.cost import build_long_report, unresolved_visual_warnings
    from pipeline.parser_long import parse_long_script
    from pipeline.tts import TTSEngine

    plan = [
        Visual(key="lebron three pointer", kind="clip",
               path=settings.cache_dir / "f.mp4", is_video=True, source="filler"),
        Visual(key="tumbleweed", kind="clip",
               path=settings.cache_dir / "g.mp4", is_video=True, source="pexels"),
    ]
    said = unresolved_visual_warnings(plan)
    assert len(said) == 1, "only the miss is worth the operator's attention"
    assert "lebron three pointer" in said[0]
    assert "Giphy" in said[0] and "Tenor" in said[0], \
        "the operator has to know the whole chain missed, not just Pexels"

    script, warnings = parse_long_script(long_valid_text, "EXMPL", settings)
    report = build_long_report(script, warnings, [], [], settings,
                               SpendLedger(settings), TTSEngine(settings),
                               plan, 0)
    text = report.render_text()
    assert said[0] in report.warnings
    assert f"⚠️ {said[0]}" in text, "it has to reach the rendered report"
    assert report.approvable, "a missing illustration warns; it never blocks"


# --------------------------------------------------------------------------
# A2 — /cost must not contradict itself. The thing that decides whether the
# voice spends is `mocking_tts` (which follows MOCK_TTS), not MOCK_MODE.
# --------------------------------------------------------------------------


def test_cost_does_not_claim_zero_spend_while_the_paid_voice_is_live(settings):
    """MOCK_MODE=true with MOCK_TTS=false is a live ElevenLabs."""
    from bot.handlers import BotCore

    live_voice = settings.model_copy(update={"mock_mode": True, "mock_tts": False})
    text = BotCore(live_voice).cost_text()

    assert "TTS: live" in text
    assert "no paid calls possible" not in text, \
        "the voice is live; the mode line said it could not be"


def test_cost_says_no_paid_calls_when_nothing_can_spend(settings):
    from bot.handlers import BotCore

    both_mocked = settings.model_copy(update={"mock_mode": True, "mock_tts": True})
    text = BotCore(both_mocked).cost_text()

    assert "no paid calls possible" in text
    assert "TTS: MOCK" in text


# --------------------------------------------------------------------------
# P7 — the number that matters carries its own age.
# --------------------------------------------------------------------------


def test_cost_says_nobody_has_ever_reconciled_it(settings):
    """P7: every figure in `/cost` is what Dennis BELIEVES it spent —
    chunks counted at the configured rate, against a cap enforced from the
    same number. Nothing reconciles it against the provider, so a drift is
    invisible from inside and the first symptom is a bill. Silence about
    that is the same failure the provenance record exists to prevent."""
    from bot.handlers import BotCore

    text = BotCore(settings).cost_text()
    assert "Reconciled: NEVER" in text
    assert "/cost reconciled" in text


def test_marking_it_reconciled_stamps_a_date_that_survives_a_restart(settings):
    """It is a date on disk, not a claim about correctness."""
    import datetime

    from bot.handlers import BotCore
    from pipeline.cost import SpendLedger

    core = BotCore(settings)
    reply = core.mark_reconciled()
    today = datetime.date.today().isoformat()
    assert today in reply
    # It says outright what it is not.
    assert "does not verify anything" in reply

    # A fresh ledger over the same state dir reads it back.
    assert SpendLedger(settings).reconciled_on() == today
    assert "Reconciled: today" in BotCore(settings).cost_text()


def test_an_old_reconciliation_marks_itself_stale(settings):
    """A date nobody looks at is the thing this replaces, so the line has to
    change shape once it is old rather than sitting there looking current."""
    import datetime

    from pipeline.cost import SpendLedger

    ledger = SpendLedger(settings)
    today = datetime.date(2026, 9, 12)

    ledger.mark_reconciled(datetime.date(2026, 9, 10))
    fresh = ledger.reconciled_line(today)
    assert "2 days ago" in fresh and "stale" not in fresh

    ledger.mark_reconciled(datetime.date(2026, 7, 1))
    old = ledger.reconciled_line(today)
    assert "73 days ago" in old
    assert "⚠️ stale" in old, "an old check must not read as a current one"
    assert old != fresh


def test_the_command_routes_reconciled_and_refuses_anything_else(settings):
    """`/cost` and `/cost reconciled` are the whole surface; a typo must not
    silently print the report as if it had been understood."""
    from bot.handlers import BotCore

    core = BotCore(settings)
    assert "Month-to-date" in core.cost_reply([]).text
    assert "Month-to-date" in core.cost_reply(None).text

    stamped = core.cost_reply(["reconciled"])
    assert "marked reconciled" in stamped.text
    assert "Reconciled: today" in core.cost_reply([]).text

    for typo in (["reconsiled"], ["reset"], ["--help"]):
        out = core.cost_reply(typo).text
        assert out.startswith("usage:"), f"{typo} was not refused: {out}"
        assert "Month-to-date" not in out


# --------------------------------------------------------------------------
# Reservations.
#
# The cap is the only hard stop in this system, and it used to be
# check-then-act: `guard_tts_spend` read the month-to-date, let the lock go,
# and the generation it authorised recorded its spend minutes later. Nothing
# concurrent reaches it today — one queue worker — which is exactly why these
# tests exist: the defect is invisible until the day it is not.
# --------------------------------------------------------------------------


def test_a_reservation_counts_against_the_cap_before_it_is_spent(settings):
    """The second job must not be authorised against the first job's money."""
    settings = settings.model_copy(update={"monthly_spend_cap_usd": 1.0})
    ledger = SpendLedger(settings)
    chars = int(0.6 / settings.tts_usd_per_1k_chars * 1000)

    est, token = ledger.reserve_tts_spend(chars)
    assert est == pytest.approx(0.6, abs=0.01)
    assert ledger.reserved_usd() == pytest.approx(est, abs=1e-4)
    assert ledger.mtd_spend_usd() == 0.0, "a reservation is not a charge"

    with pytest.raises(SpendCapExceededError) as e:
        ledger.reserve_tts_spend(chars)
    assert "already running" in str(e.value)

    ledger.release_reservation(token)
    assert ledger.reserved_usd() == 0.0
    ledger.reserve_tts_spend(chars)  # the headroom came back


def test_a_released_reservation_leaves_the_real_spend_alone(settings):
    """Release gives back the CLAIM. What was billed is already recorded."""
    ledger = SpendLedger(settings)
    _est, token = ledger.reserve_tts_spend(1000)
    ledger.record_tts(0.25)
    spent = ledger.mtd_spend_usd()
    ledger.release_reservation(token)
    assert ledger.mtd_spend_usd() == spent
    assert ledger.reserved_usd() == 0.0


def test_an_abandoned_reservation_does_not_eat_the_cap_forever(settings):
    """A process killed mid-generation leaves its claim behind. Without a
    sweep that claim holds cap headroom until the month rolls over."""
    import json
    from datetime import datetime, timezone

    settings = settings.model_copy(update={"monthly_spend_cap_usd": 1.0})
    ledger = SpendLedger(settings)
    ledger.reserve_tts_spend(int(0.9 / settings.tts_usd_per_1k_chars * 1000))
    assert ledger.reserved_usd() > 0.5

    data = json.loads(ledger.path.read_text(encoding="utf-8"))
    stale = datetime.now(timezone.utc).timestamp() - SpendLedger._RESERVATION_TTL_S - 1
    for r in data[month_key()]["reservations"]:
        r["at"] = stale
    ledger.path.write_text(json.dumps(data), encoding="utf-8")

    assert ledger.reserved_usd() == 0.0
    ledger.reserve_tts_spend(1000)  # and the cap is usable again


def test_the_guard_still_answers_the_question_without_holding_the_money(settings):
    """`guard_tts_spend` keeps its old contract for callers that only ask."""
    ledger = SpendLedger(settings)
    est = ledger.guard_tts_spend(1000)
    assert est == pytest.approx(estimate_tts_usd(1000, settings))
    assert ledger.reserved_usd() == 0.0, "asking is not claiming"

    small = settings.model_copy(update={"monthly_spend_cap_usd": 0.0001})
    with pytest.raises(SpendCapExceededError):
        SpendLedger(small).guard_tts_spend(100_000)


def test_every_ledger_in_the_process_shares_one_lock(settings):
    """`BotCore` builds one and hands it to the TTS engine and the b-roll
    manager; a per-instance lock guards nothing when the file is shared."""
    assert SpendLedger(settings)._lock is SpendLedger(settings)._lock


# --------------------------------------------------------------------------
# The cross-process lock, the weekly ceiling, and where the month went.
# --------------------------------------------------------------------------


def test_the_lock_is_shared_per_ledger_file(settings):
    """Two ledgers on one file must share one lock — `flock` contends between
    descriptors even inside a process, so two of them would deadlock against
    each other rather than against a second process."""
    from pipeline.cost import SpendLedger

    assert SpendLedger(settings)._lock is SpendLedger(settings)._lock


def test_the_lock_is_reentrant(settings):
    """`reserve_tts_spend` takes it and calls `_live_reservations`, which
    takes it again. A file lock that was not reentrant would hang here."""
    from pipeline.cost import SpendLedger

    ledger = SpendLedger(settings)
    with ledger._lock:
        with ledger._lock:
            assert ledger.reserved_usd() == 0.0


def test_a_second_process_cannot_claim_the_same_headroom(settings):
    """The whole point: the lockfile is held while the ledger is read and
    written, so another process blocks rather than reading a stale total."""
    import fcntl

    from pipeline.cost import SpendLedger

    ledger = SpendLedger(settings)
    ledger.record_tts(1.0)
    lock_path = settings.state_dir / "spend.lock"
    assert lock_path.exists(), "the lockfile is taken on a write"

    with ledger._lock:
        # While it is held, a foreign descriptor cannot take it.
        with open(lock_path, "a+", encoding="utf-8") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_the_week_key_is_iso_so_a_straddling_week_stays_one_week():
    from datetime import datetime, timezone

    from pipeline.cost import week_key

    # 2026-12-31 and 2027-01-01 are the same ISO week.
    a = week_key(datetime(2026, 12, 31, tzinfo=timezone.utc))
    b = week_key(datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert a == b


def test_the_weekly_warning_is_silent_until_the_mark(settings):
    from pipeline.cost import SpendLedger

    settings.weekly_spend_warn_usd = 10.0
    ledger = SpendLedger(settings)
    ledger.record_tts(4.0, lane="short", ticker="AAPL")
    assert ledger.weekly_warning() == ""

    ledger.record_tts(7.0, lane="short", ticker="MSFT")
    warning = ledger.weekly_warning()
    assert "past the $10.00 weekly mark" in warning


def test_the_weekly_warning_can_be_asked_about_one_lane(settings):
    from pipeline.cost import SpendLedger

    settings.weekly_spend_warn_usd = 5.0
    ledger = SpendLedger(settings)
    ledger.record_tts(6.0, lane="long", ticker="AAPL")

    assert "on the long lane" in ledger.weekly_warning(lane="long")
    assert ledger.weekly_warning(lane="short") == ""


def test_a_zero_ceiling_turns_the_weekly_warning_off(settings):
    from pipeline.cost import SpendLedger

    settings.weekly_spend_warn_usd = 0.0
    ledger = SpendLedger(settings)
    ledger.record_tts(999.0, lane="short")
    assert ledger.weekly_warning() == ""


def test_explain_says_where_the_month_went(settings):
    from pipeline.cost import SpendLedger

    ledger = SpendLedger(settings)
    ledger.record_tts(3.0, lane="short", ticker="AAPL", chars=800, tier="paid")
    ledger.record_tts(1.0, lane="long", ticker="MSFT", chars=200, tier="paid")

    text = ledger.explain_text()

    assert "By video" in text and "By tier" in text
    assert "AAPL" in text and "MSFT" in text
    assert "$  3.00" in text


def test_explain_counts_the_cache_as_money_not_spent(settings):
    from pipeline.cost import SpendLedger

    ledger = SpendLedger(settings)
    ledger.record_cache_hit(5000, lane="short", ticker="AAPL", tier="paid")

    text = ledger.explain_text()

    assert "cache answered 1 generation" in text
    assert ledger.mtd_spend_usd() == 0.0, "a cache hit spends nothing"


def test_explain_is_honest_about_an_empty_month(settings):
    from pipeline.cost import SpendLedger

    assert "No paid generation recorded" in SpendLedger(settings).explain_text()
