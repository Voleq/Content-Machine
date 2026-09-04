"""Standing state (P3.3): thesis tracking, idea queue, multi-clip, batch.

Every session used to start from a blank page. These four things are what the
bot now remembers between them, and the property they share is that a
bookkeeping failure must never break the real work — a screen still screens, a
shipped video still ships.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipeline.workspace import Workspace, today_str
from pipeline.standing import (
    BatchQueue,
    IdeaQueue,
    Move,
    ThesisBook,
    ideas_from_thesis_moves,
    in_batch_window,
    update_warranted,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeData:
    """Stands in for CompanyData: a snapshot plus an optional history."""

    def __init__(self, values: dict, history: dict | None = None):
        self.values = values
        self.history = history or {}

    def get(self, key):
        return self.values.get(key)


# --------------------------------------------------------------------------
# Thesis tracking.
# --------------------------------------------------------------------------


def test_a_thesis_pins_the_numbers_it_rests_on(settings):
    book = ThesisBook(settings)
    data = FakeData({"price": 10.0, "market_cap": 1e9, "gross_margin": 0.40})
    t = book.record("exmpl", "cheap for a reason", data)
    assert t.ticker == "EXMPL"
    assert t.numbers["price"] == 10.0
    assert t.numbers["gross_margin"] == 0.40
    assert book.get("EXMPL").summary == "cheap for a reason"


def test_it_survives_a_restart(settings):
    ThesisBook(settings).record("EXMPL", "the thesis", FakeData({"price": 10.0}))
    assert ThesisBook(settings).get("EXMPL") is not None


def test_a_small_drift_is_not_reported(settings):
    """Reporting every wiggle is how you train the operator to ignore the
    notification — the real failure mode of anything that watches numbers."""
    book = ThesisBook(settings)
    book.record("EXMPL", "t", FakeData({"price": 10.0, "gross_margin": 0.40}))
    _, moves = book.check("EXMPL", FakeData({"price": 10.4, "gross_margin": 0.41}))
    assert moves == []
    assert book.get("EXMPL").status == "intact"


def test_a_material_move_is_reported_with_the_numbers(settings):
    book = ThesisBook(settings)
    book.record("EXMPL", "t", FakeData({"price": 10.0}))
    _, moves = book.check("EXMPL", FakeData({"price": 5.0}))
    assert len(moves) == 1
    rendered = moves[0].render()
    assert "price" in rendered and "50%" in rendered and "↓" in rendered


def test_thresholds_differ_by_metric(settings):
    """A margin moving 3 points is not the same event as a price moving 3%."""
    book = ThesisBook(settings)
    book.record("EXMPL", "t", FakeData({"price": 10.0, "gross_margin": 0.40}))
    # +8% on both: nothing for the price, material for the margin
    _, moves = book.check("EXMPL", FakeData({"price": 10.8, "gross_margin": 0.432}))
    assert [m.field for m in moves] == ["gross_margin"]


def test_the_status_escalates_with_the_damage(settings):
    book = ThesisBook(settings)
    base = {"price": 10.0, "gross_margin": 0.40, "fcf": 100.0, "shares_out": 50.0}
    book.record("EXMPL", "t", FakeData(base))

    book.check("EXMPL", FakeData({**base, "gross_margin": 0.30}))
    assert book.get("EXMPL").status == "cracking"

    book.check("EXMPL", FakeData({**base, "gross_margin": 0.20, "fcf": 40.0,
                                  "shares_out": 70.0}))
    assert book.get("EXMPL").status == "broken"


def test_a_number_that_vanished_is_skipped_not_treated_as_zero(settings):
    """A missing field in a thin export must not read as a 100% collapse."""
    book = ThesisBook(settings)
    book.record("EXMPL", "t", FakeData({"price": 10.0, "fcf": 100.0}))
    _, moves = book.check("EXMPL", FakeData({"price": 10.0}))
    assert moves == []


def test_history_is_used_when_the_snapshot_lacks_the_field(settings):
    book = ThesisBook(settings)
    data = FakeData({"price": 10.0}, history={"fcf": [50.0, 80.0, 100.0]})
    t = book.record("EXMPL", "t", data)
    assert t.numbers["fcf"] == 100.0, "the latest period, not the first"


def test_checking_an_unknown_ticker_is_not_an_error(settings):
    t, moves = ThesisBook(settings).check("NOPE", FakeData({"price": 1.0}))
    assert t is None and moves == []


def test_the_update_notice_names_what_moved():
    moves = [Move("price", 10.0, 5.0), Move("fcf", 100.0, 40.0)]
    text = update_warranted(moves)
    assert "update video is warranted" in text
    assert "price" in text and "fcf" in text


def test_no_moves_means_no_notice():
    assert update_warranted([]) == ""


# --------------------------------------------------------------------------
# The idea queue.
# --------------------------------------------------------------------------


def test_the_queue_ranks_by_source_then_score(settings):
    q = IdeaQueue(settings)
    q.add("AAA", "screened", "screener", score=1.0)
    q.add("BBB", "thesis moved", "thesis", score=1.0)
    q.add("CCC", "operator pick", "operator", score=1.0)
    order = [i.ticker for i in q.ranked()]
    assert order[0] == "BBB", "a thesis trigger is the strongest signal"
    assert order.index("CCC") < order.index("AAA")


def test_a_ticker_appears_once_however_often_it_is_screened(settings):
    """The screener runs daily and a beaten-down name stays beaten down;
    without de-duplication the queue becomes the same twenty names."""
    q = IdeaQueue(settings)
    for day in range(5):
        q.add("EXMPL", f"still cheap on day {day}", "screener")
    rows = q.ranked(50)
    assert len([i for i in rows if i.ticker == "EXMPL"]) == 1
    assert "day 4" in rows[0].reason, "the newest reason wins"


def test_seen_ideas_drop_out_of_the_default_view(settings):
    q = IdeaQueue(settings)
    q.add("EXMPL", "r", "screener")
    q.mark_seen("EXMPL")
    assert q.ranked() == []
    assert len(q.ranked(include_seen=True)) == 1


def test_stale_ideas_are_pruned(settings):
    """A three-week-old "it moved 9% today" is not an idea."""
    q = IdeaQueue(settings)
    q.add("OLD", "moved 9% today", "screener")
    rows = json.loads(q.path.read_text(encoding="utf-8"))
    rows[0]["added_at"] = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    q.path.write_text(json.dumps(rows), encoding="utf-8")
    q.add("NEW", "fresh", "screener")

    assert q.prune(30) == 1
    assert [i.ticker for i in q.ranked()] == ["NEW"]


def test_dropping_and_rendering(settings):
    q = IdeaQueue(settings)
    assert "empty" in q.render()
    q.add("EXMPL", "worth a look", "screener", lane="long")
    assert "EXMPL" in q.render() and "[long]" in q.render()
    assert q.drop("EXMPL") is True
    assert q.drop("EXMPL") is False


def test_a_moved_thesis_becomes_the_strongest_idea(settings):
    ideas_from_thesis_moves(settings, "EXMPL", [Move("price", 10.0, 5.0)])
    top = IdeaQueue(settings).ranked()[0]
    assert top.ticker == "EXMPL"
    assert top.source == "thesis"
    assert "price" in top.reason


def test_a_screen_feeds_the_queue_without_being_able_to_break_it(settings, monkeypatch):
    """Bookkeeping must never break a screen."""
    import pipeline.screener as screener_mod

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(screener_mod, "_save_last_screen", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.standing.ideas_from_screen", boom)
    # the import inside run_screen resolves at call time, so patching the
    # module attribute is what the code will actually see
    result = screener_mod.run_screen(settings, lane="trending")
    assert "trending" in result


# --------------------------------------------------------------------------
# Multi-clip repurpose.
# --------------------------------------------------------------------------


def _cues(times: list[float], kind: str = "meme") -> list[dict]:
    return [{"t": t, "kind": kind} for t in times]


def test_three_windows_come_back_not_one():
    from pipeline.repurpose import pick_best_windows

    cues = _cues([30, 32, 35, 200, 205, 400, 405, 410])
    windows = pick_best_windows(cues, duration=600.0, n=3)
    assert len(windows) == 3
    assert all(e > s for s, e in windows)


def test_the_windows_do_not_overlap(settings):
    """The two highest scores are almost always the same moment two seconds
    apart, which would ship as two near-identical shorts."""
    from pipeline.repurpose import pick_best_windows

    cues = _cues([100, 101, 102, 103, 104, 300, 500])
    windows = pick_best_windows(cues, duration=600.0, n=3)
    for (s1, e1), (s2, e2) in zip(windows, windows[1:]):
        assert e1 <= s2 or e2 <= s1, (windows,)


def test_a_short_long_yields_fewer_clips_rather_than_duplicates():
    from pipeline.repurpose import pick_best_windows

    windows = pick_best_windows(_cues([10, 20]), duration=50.0, n=3)
    assert len(windows) == 1
    assert windows[0] == (0.0, 50.0)


def test_the_best_window_is_still_first():
    from pipeline.repurpose import pick_best_window, pick_best_windows

    cues = _cues([300, 302, 305, 308, 30, 500])
    best = pick_best_window(cues, duration=600.0)
    assert pick_best_windows(cues, duration=600.0, n=3)[0] == best


# --------------------------------------------------------------------------
# The overnight batch.
# --------------------------------------------------------------------------


def test_queued_work_survives_the_machine_being_off(settings):
    """The design constraint: this is a desktop that sleeps, so a batch that
    did not run must be a non-event."""
    b = BatchQueue(settings)
    b.add("EXMPL", "long")
    assert [i.ticker for i in BatchQueue(settings).pending()] == ["EXMPL"]
    # …days later, still there
    assert len(BatchQueue(settings).pending()) == 1


def test_a_ticker_is_not_queued_twice(settings):
    b = BatchQueue(settings)
    b.add("EXMPL", "long")
    b.add("EXMPL", "long")
    assert len(b.pending()) == 1
    b.add("EXMPL", "short")
    assert len(b.pending()) == 2, "a different format is different work"


def test_done_items_leave_the_pending_list(settings):
    b = BatchQueue(settings)
    b.add("EXMPL", "long")
    b.mark_done("EXMPL", "long")
    assert b.pending() == []


def test_the_window_can_cross_midnight(settings):
    """"Overnight" normally does, and it is the easy thing to get wrong."""
    s = settings.model_copy(update={"batch_start_hour": 23, "batch_end_hour": 6})
    assert in_batch_window(s, datetime(2026, 7, 26, 23, 30))
    assert in_batch_window(s, datetime(2026, 7, 26, 2, 0))
    assert not in_batch_window(s, datetime(2026, 7, 26, 12, 0))


def test_a_normal_window_still_works(settings):
    s = settings.model_copy(update={"batch_start_hour": 1, "batch_end_hour": 7})
    assert in_batch_window(s, datetime(2026, 7, 26, 3, 0))
    assert not in_batch_window(s, datetime(2026, 7, 26, 23, 0))


def test_the_batch_view_says_what_happens_when_the_box_is_off(settings):
    b = BatchQueue(settings)
    assert "nothing queued" in b.render()
    b.add("EXMPL", "long")
    text = b.render()
    assert "EXMPL LONG" in text
    assert "if the machine is off" in text


# --------------------------------------------------------------------------
# The bot surface.
# --------------------------------------------------------------------------


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def test_the_queue_command_tells_you_what_to_do_with_it(core, settings):
    IdeaQueue(settings).add("EXMPL", "beaten down", "screener", lane="long")
    reply = core.queue_text()
    assert "EXMPL" in reply.text
    assert "/long TICKER" in reply.text


def test_an_empty_queue_says_how_to_fill_it(core):
    assert "/screen" in core.queue_text().text


def test_the_operator_can_add_and_drop_ideas(core, settings):
    assert "queued EXMPL" in core.queue_add(["EXMPL", "gut", "feel"]).text
    assert IdeaQueue(settings).ranked()[0].source == "operator"
    assert "dropped" in core.queue_drop(["EXMPL"]).text


def test_thesis_with_no_argument_lists_what_is_covered(core, settings):
    assert "No theses" in core.thesis_text([]).text
    ThesisBook(settings).record("EXMPL", "cheap for a reason",
                                FakeData({"price": 10.0}))
    text = core.thesis_text([]).text
    assert "EXMPL" in text and "cheap for a reason" in text


def test_thesis_for_one_ticker_rechecks_against_todays_numbers(core, settings):
    import shutil

    core.start_lane(1, "long", "EXMPL")
    ws = core.context.get(1)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    # a thesis pinned at an absurd price, so today's number is a big move
    ThesisBook(settings).record("EXMPL", "the thesis", FakeData({"price": 1000.0}))

    reply = core.thesis_text(["EXMPL"])
    assert "THESIS:" in reply.text
    assert "moved" in reply.text
    assert IdeaQueue(settings).ranked()[0].source == "thesis", \
        "a broken thesis should feed the backlog"


def test_the_batch_command_queues_and_reports(core, settings):
    assert "nothing queued" in core.batch_text([]).text
    reply = core.batch_text(["EXMPL", "long"])
    assert "EXMPL LONG queued" in reply.text
    assert "cleared 1" in core.batch_text(["clear"]).text


def test_the_batch_plan_reports_what_it_cannot_run_rather_than_dropping_it(
        core, settings):
    """A batch that silently skipped the render you cared about is worse than
    no batch."""
    BatchQueue(settings).add("NOSUCH", "long")
    submittable, skipped, _note = core.batch_plan()
    assert submittable == []
    assert len(skipped) == 1 and "NOSUCH" in skipped[0]


def test_the_batch_can_be_switched_off(core, settings):
    BatchQueue(settings).add("EXMPL", "long")
    core.settings = settings.model_copy(update={"batch_enabled": False})
    submittable, _skipped, note = core.batch_plan()
    assert submittable == []
    assert "switched off" in note


def test_shipping_a_video_pins_the_thesis(core, settings, long_valid_text):
    """At ship time, because that is when the claim becomes public."""
    import shutil
    from pipeline.models import JobKind, JobRecord

    core.start_lane(2, "long", "EXMPL")
    ws = core.context.get(2)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    core.intake_script(2, long_valid_text)
    ws.set_chosen_angle("the value trap that isn't")

    job = JobRecord(id="j1", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                    workdate=ws.workdate)
    core._record_thesis(job)

    t = ThesisBook(settings).get("EXMPL")
    assert t is not None
    assert "value trap" in t.summary
    assert t.numbers, "the numbers behind it were pinned too"


def test_thesis_bookkeeping_cannot_fail_a_shipped_video(core, settings, monkeypatch):
    """A delivered video must never be turned into a failed job by bookkeeping."""
    from pipeline.models import JobKind, JobRecord
    import pipeline.standing as standing

    monkeypatch.setattr(standing.ThesisBook, "record",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    job = JobRecord(id="j2", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                    workdate="2026-07-26")
    core._record_thesis(job)          # must not raise


# --------------------------------------------------------------------------
# What the bot remembers about a stock between videos (Stage B).
# --------------------------------------------------------------------------


OLD_SCHEMA = {
    "EXMPL": {
        "ticker": "EXMPL",
        "summary": "cheap for a reason, and the reason hasn't changed",
        "numbers": {"price": 10.0, "gross_margin": 0.40},
        "recorded_at": "2026-05-01T09:00:00+00:00",
        "workdate": "2026-05-01",
        "status": "intact",
        "checked_at": "",
        "last_moves": [],
    }
}


def test_a_thesis_written_by_an_older_build_still_loads(settings):
    """The one that protects live state.

    There is a theses.json on the operator's disk written before `hook`,
    `conclusion`, `claims` and `fmt` existed. A schema change that drops it is
    a real regression — the module's own premise is that the interesting
    failure is a reboot mid-week, not a migration.
    """
    book = ThesisBook(settings)
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps(OLD_SCHEMA), encoding="utf-8")

    t = book.get("EXMPL")
    assert t is not None
    assert t.summary.startswith("cheap for a reason")
    assert t.numbers["price"] == 10.0
    # the new fields are absent, not wrong
    assert t.hook == "" and t.conclusion == "" and t.claims == [] and t.fmt == ""


def test_a_row_from_a_newer_build_does_not_take_the_book_down(settings):
    """The other direction: a field this build has never heard of is dropped,
    not raised on. One unknown key must not cost every thesis on file."""
    book = ThesisBook(settings)
    book.path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(OLD_SCHEMA["EXMPL"], something_from_the_future="hello")
    book.path.write_text(json.dumps({"EXMPL": row}), encoding="utf-8")
    assert book.get("EXMPL").summary.startswith("cheap for a reason")


def test_the_widened_record_round_trips(settings):
    book = ThesisBook(settings)
    book.record("exmpl", "the value trap", FakeData({"price": 10.0}),
                hook="EXMPL is up 29% today. The business is not.",
                conclusion="Noise. Set a reminder for the next 10-Q.",
                claims=["Revenue has flatlined", "The share count grows 6% a year"],
                fmt="short")

    t = ThesisBook(settings).get("EXMPL")     # a fresh book: off disk, not memory
    assert t.hook.startswith("EXMPL is up 29%")
    assert t.conclusion == "Noise. Set a reminder for the next 10-Q."
    assert t.claims == ["Revenue has flatlined",
                        "The share count grows 6% a year"]
    assert t.fmt == "short"
    # and a check() still writes it back without losing any of it
    ThesisBook(settings).check("EXMPL", FakeData({"price": 30.0}))
    assert ThesisBook(settings).get("EXMPL").conclusion.startswith("Noise.")


def test_a_short_records_its_own_structured_fields(short_valid_json, settings):
    from bot.handlers import _what_it_said
    from pipeline.parser_short import parse_short_script

    script, _ = parse_short_script(short_valid_json, settings)
    said = _what_it_said(script, "short")
    assert said["hook"] == script.hook_text
    assert said["conclusion"] == script.conclusion
    assert script.numbers_comment in said["claims"]


def test_a_long_records_a_conclusion_from_its_last_two_sentences(
        long_valid_text, settings):
    """LongScript carries only narration and the chapter trailer, so the
    closing claim has to be read back out of the prose. The format ends on
    the verdict, which is what makes the last two sentences the right ones."""
    from bot.handlers import _what_it_said
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    said = _what_it_said(script, "long")
    assert said["conclusion"], "the long path produced no conclusion"
    assert said["conclusion"] in script.narration.replace("\n", " ") or \
        said["conclusion"].split()[-1] in script.narration
    assert said["hook"], "the long path produced no hook"


def test_reading_back_a_missing_script_is_not_an_error():
    from bot.handlers import _what_it_said

    assert _what_it_said(None, "long") == {}
    assert _what_it_said(None, "short") == {}


def test_prior_coverage_is_empty_when_nothing_is_on_file(settings):
    """A name we have never covered has nothing to say, and a heading over an
    empty block is worse than no heading."""
    from bot.prompts import prior_coverage

    assert prior_coverage(settings, "NEVER") == ""
    assert prior_coverage(settings, "") == ""


def test_prior_coverage_renders_an_old_record_without_inventing_fields(settings):
    """A writer told "the conclusion is not on file" writes around it. A
    writer told nothing invents a conclusion that was never made and then
    grades the channel against a claim it never put on screen."""
    from bot.prompts import prior_coverage

    book = ThesisBook(settings)
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps(OLD_SCHEMA), encoding="utf-8")

    block = prior_coverage(settings, "exmpl")
    assert "PRIOR COVERAGE" in block
    assert "cheap for a reason" in block
    assert "2026-05-01" in block
    assert "NOT ON FILE" in block
    assert "the conclusion" in block and "the specific claims" in block
    assert "do NOT invent them" in block
    assert "VERBATIM" not in block, "it has no conclusion — it must not print one"


def test_prior_coverage_carries_the_claims_and_what_moved(settings):
    from bot.prompts import prior_coverage

    book = ThesisBook(settings)
    book.record("EXMPL", "the value trap", FakeData({"gross_margin": 0.744}),
                workdate="2026-05-01", fmt="long",
                hook="Revenue has not moved in five years.",
                conclusion="Noise. Set a reminder for the next 10-Q.",
                claims=["Margins hold", "The buyback is real"])
    book.check("EXMPL", FakeData({"gross_margin": 0.652}))

    block = prior_coverage(settings, "EXMPL")
    assert "(LONG)" in block
    assert 'It concluded, VERBATIM: "Noise. Set a reminder for the next 10-Q."' in block
    assert "- Margins hold" in block and "- The buyback is real" in block
    assert "Thesis status: cracking" in block
    # rendered by Move.render(), not by a second formatter
    assert "gross_margin ↓12%" in block
    assert "NOT ON FILE" not in block


def test_prior_coverage_survives_an_unreadable_book(settings, monkeypatch):
    """It is injected into a prompt. It never blocks one."""
    from bot.prompts import prior_coverage

    book = ThesisBook(settings)
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text("{not json", encoding="utf-8")
    assert prior_coverage(settings, "EXMPL") == ""


# --------------------------------------------------------------------------
# The update prompt — its own format, not the first-time one with history.
# --------------------------------------------------------------------------


@pytest.fixture()
def covered(settings, workspace):
    """A workspace for a ticker with a real thesis on file, already checked."""
    book = ThesisBook(settings)
    book.record("EXMPL", "cheap for a reason, and the reason hasn't changed",
                FakeData({"gross_margin": 0.744, "price": 10.0}),
                workdate="2026-05-01", fmt="long",
                hook="Revenue has not moved in five years.",
                conclusion="Noise. A press release and a squeeze, stapled to "
                           "five years of drift.",
                claims=["The margin is the thesis",
                        "Capital allocation: the buyback that is not one"])
    book.check("EXMPL", FakeData({"gross_margin": 0.652, "price": 13.4}))
    return workspace


def test_the_update_prompt_fills_end_to_end(settings, covered):
    import re

    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data

    text = fill_prompt("update", "EXMPL", load_company_data(covered), covered,
                       settings)
    left = [m for m in re.findall(r"\{\{[a-z_]+\}\}", text)
            if m != "{{placeholder}}"]
    assert not left, f"unfilled placeholders: {left}"
    # the previous video is the SPINE, not an appendix
    assert "PRIOR COVERAGE" in text
    assert 'It concluded, VERBATIM: "Noise. A press release' in text
    assert "gross_margin ↓12%" in text
    # the four movements, in order
    for i, movement in enumerate(("WHAT I SAID", "WHAT HAPPENED",
                                  "WAS I RIGHT", "WHAT NOW")):
        assert movement in text, movement
    order = [text.index(m) for m in ("WHAT I SAID", "WHAT HAPPENED",
                                     "WAS I RIGHT", "WHAT NOW")]
    assert order == sorted(order), "the movements are out of order"
    # it inherits the bible and the tag grammar unchanged
    assert "Dennis — voice bible" in text
    assert "[SHOW FILING: file.png]" in text
    assert "=== CHAPTERS ===" in text


def test_the_update_prompt_refuses_to_let_a_miss_be_hedged(settings, covered):
    """The one failure mode of the format: a miss laundered into a near-hit."""
    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data

    text = fill_prompt("update", "EXMPL", load_company_data(covered), covered,
                       settings)
    assert "broadly the direction we identified" in text, \
        "the hedge has to be named to be banned"
    assert "I was wrong about" in text
    assert "THESIS: BROKEN" in text


def test_the_update_prompt_is_not_the_long_prompt(settings, covered):
    """A different spine, not the first-time brief with history glued on."""
    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data

    data = load_company_data(covered)
    update = fill_prompt("update", "EXMPL", data, covered, settings)
    long = fill_prompt("long_write", "EXMPL", data, covered, settings,
                       chosen_angle="the value trap")
    assert "THE FOUR MOVEMENTS" in update and "THE FOUR MOVEMENTS" not in long
    assert "THE CHOSEN ANGLE" in long and "THE CHOSEN ANGLE" not in update
    assert "STEP A — HOOK OPTIONS" in long and "STEP A" not in update
    # an update is narrower, so it is shorter than the deep dive it follows
    assert len(update) < len(long)


def test_an_uncovered_ticker_says_so_rather_than_faking_a_history(
        settings, workspace):
    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data

    text = fill_prompt("update", "NEVER", load_company_data(workspace),
                       workspace, settings)
    assert "no thesis on file" in text
    assert "/long TICKER" in text
    assert "PRIOR COVERAGE" not in text


# --------------------------------------------------------------------------
# /update — the trigger names the action, and the action is explicit.
# --------------------------------------------------------------------------


def test_the_notice_names_the_command_not_just_the_conclusion(settings):
    """"An update video is warranted" told the operator a conclusion and left
    them to work out what to type. What they typed was /long."""
    moves = [Move(field="gross_margin", before=0.744, after=0.652)]
    assert "/update EXMPL" in update_warranted(moves, "exmpl")
    # and it still stands alone when nobody passed a ticker
    assert "warranted" in update_warranted(moves)


def test_update_on_an_uncovered_ticker_points_at_long(core, settings):
    reply = core.start_lane(1, "long", "NEVER", update=True)
    assert "No thesis on file" in reply.text
    assert "/long NEVER" in reply.text
    ws = Workspace(settings, "NEVER", today_str())
    assert not ws.path.exists(), "it must not open a workspace it cannot fill"


def test_update_opens_a_long_workspace_with_no_angle_step(core, settings):
    ThesisBook(settings).record("EXMPL", "the value trap",
                                FakeData({"price": 10.0}))
    reply = core.start_lane(1, "long", "EXMPL", update=True)
    assert "UPDATE" in reply.text

    ws = Workspace(settings, "EXMPL", today_str())
    assert ws.lane() == "long", "an update renders as a long"
    assert ws.is_update()
    assert not ws.awaiting_angle(), "an update has no angle to pick"
    assert ws.current_format() == "long", \
        "the render path must still see a plain long"


def test_a_plain_long_is_not_an_update(core, settings):
    core.start_lane(1, "long", "EXMPL")
    ws = Workspace(settings, "EXMPL", today_str())
    assert not ws.is_update()
    assert ws.awaiting_angle()


def test_the_update_workspace_hands_back_the_update_prompt(core, settings, tmp_path):
    import shutil

    ThesisBook(settings).record("EXMPL", "the value trap",
                                FakeData({"price": 10.0}), fmt="long",
                                conclusion="Noise.", claims=["The margin is the thesis"])
    core.start_lane(1, "long", "EXMPL", update=True)
    ws = Workspace(settings, "EXMPL", today_str())
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")

    reply = core.prompts_reply(1)
    assert "UPDATE" in reply.text
    names = [f.name for f in reply.files]
    assert names == ["prompt_update.md"], names
    assert "THE FOUR MOVEMENTS" in (ws.path / "prompt_update.md").read_text(
        encoding="utf-8")


def test_the_help_text_offers_it(core):
    from bot.handlers import HELP_TEXT

    assert "/update TICKER" in HELP_TEXT


# --------------------------------------------------------------------------
# The cooldown suppresses fresh coverage. An update is the opposite of that.
# --------------------------------------------------------------------------


def _covered_recently(settings, ticker: str) -> None:
    """A workspace dated today — which is what the cooldown reads."""
    Workspace(settings, ticker, today_str()).create()


def test_a_cooled_ticker_is_still_not_a_fresh_candidate(settings, monkeypatch):
    """The screener's own suppression is left alone: covering a name three
    weeks ago is still a reason not to pitch it as a new one."""
    from pipeline import screener

    _covered_recently(settings, "EXMPL")
    result = screener.run_screen(settings, "all")
    fresh = {c.ticker for lane in ("trending", "value")
             for c in result.get(lane, [])}
    assert "EXMPL" not in fresh


def test_a_moved_thesis_is_exempt_from_the_cooldown(settings):
    """Being recently covered is the PRECONDITION for an update, not a reason
    to skip it — and every ticker in this lane is cooled by definition."""
    from pipeline import screener

    _covered_recently(settings, "EXMPL")
    book = ThesisBook(settings)
    book.record("EXMPL", "the margin is the thesis",
                FakeData({"gross_margin": 0.744}))
    book.check("EXMPL", FakeData({"gross_margin": 0.652}))   # -12%, cracking

    result = screener.run_screen(settings, "all")
    assert "EXMPL" in result["updates"]
    assert "EXMPL" not in {c.ticker for lane in ("trending", "value")
                           for c in result.get(lane, [])}
    assert "/update EXMPL" in screener.digest_text(result)


def test_an_intact_thesis_is_not_an_update_candidate(settings):
    from pipeline import screener

    book = ThesisBook(settings)
    book.record("EXMPL", "nothing has changed", FakeData({"price": 10.0}))
    book.check("EXMPL", FakeData({"price": 10.2}))           # +2%, intact
    assert screener.run_screen(settings, "all")["updates"] == []


def test_an_unreadable_thesis_book_does_not_break_a_screen(settings):
    from pipeline import screener

    path = settings.state_dir / "theses.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    result = screener.run_screen(settings, "all")
    assert result["updates"] == []
    assert "trending" in result, "a screen still screens"


# --------------------------------------------------------------------------
# The whole loop, across every seam: ship -> remember -> tell the next writer.
# --------------------------------------------------------------------------


def test_a_shipped_short_reaches_the_next_writers_prompt(core, settings,
                                                         short_valid_json):
    """The loop used to be remember -> notify -> FORGET. Every piece of it is
    tested above in isolation; this is the one that crosses the seams, because
    every one of those seams is where it used to fall apart.
    """
    import shutil

    from bot.prompts import fill_prompt, prior_coverage
    from pipeline.company_data import load_company_data
    from pipeline.models import JobKind, JobRecord
    from pipeline.parser_short import parse_short_script

    ws = Workspace(settings, "EXMPL", today_str()).create()
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    script, _ = parse_short_script(short_valid_json, settings)
    ws.save_short(script, short_valid_json)

    # 1. it ships
    core._record_thesis(JobRecord(id="j1", kind=JobKind.RENDER_SHORT,
                                  ticker="EXMPL", workdate=ws.workdate))

    # 2. the book has what it actually said, not just a label for it
    thesis = ThesisBook(settings).get("EXMPL")
    assert thesis is not None
    assert thesis.fmt == "short"
    assert thesis.conclusion == script.conclusion
    assert thesis.hook == script.hook_text

    # 3. the writer of the next one is told
    block = prior_coverage(settings, "EXMPL")
    assert script.conclusion in block
    assert "NOT ON FILE" not in block

    # 4. and it is in the prompt they are handed
    text = fill_prompt("update", "EXMPL", load_company_data(ws.path), ws.path,
                       settings)
    assert script.conclusion in text
    assert "WHAT I SAID" in text


def test_a_shipped_long_reaches_it_too(core, settings, long_valid_text):
    """The LONG has no structured fields, so this crosses the read-back path
    that has to reconstruct the claim out of prose."""
    import shutil

    from bot.prompts import prior_coverage
    from pipeline.models import JobKind, JobRecord
    from pipeline.parser_long import parse_long_script

    ws = Workspace(settings, "EXMPL", today_str()).create()
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    ws.save_long(script, long_valid_text)
    ws.set_chosen_angle("the value trap")

    core._record_thesis(JobRecord(id="j2", kind=JobKind.RENDER_LONG,
                                  ticker="EXMPL", workdate=ws.workdate))

    thesis = ThesisBook(settings).get("EXMPL")
    assert thesis.fmt == "long"
    assert thesis.summary == "the value trap"
    assert thesis.conclusion, "the last-two-sentences path produced nothing"

    block = prior_coverage(settings, "EXMPL")
    assert thesis.conclusion in block
    assert "(LONG)" in block


def test_bookkeeping_never_fails_a_shipped_video(core, settings, monkeypatch):
    """A video that delivered must not be turned into a failed job by the
    record-keeping that runs after it."""
    from pipeline.models import JobKind, JobRecord

    ws = Workspace(settings, "EXMPL", today_str()).create()
    # no data export at all, and a script that cannot be read back
    monkeypatch.setattr(ThesisBook, "record",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    core._record_thesis(JobRecord(id="j3", kind=JobKind.RENDER_SHORT,
                                  ticker="EXMPL", workdate=ws.workdate))


# ------------------------------------------------------------ the confession ledger


def _ledger(tmp_path):
    from config import Settings
    from pipeline.standing import ConfessionLedger

    s = Settings(MOCK_MODE=True, _env_file=None)
    s = s.model_copy(update={"state_dir": tmp_path})
    return ConfessionLedger(s)


def test_a_silent_video_is_recorded_too(tmp_path):
    """"Roughly one video in three" is a question about the other two.

    A ledger holding only the admissions can say what has been used; it cannot
    say how long it has been, which is the half of the rule that decides
    whether to write one at all.
    """
    led = _ledger(tmp_path)
    assert led.videos_since_last() == 0 and not led.due()

    led.note("AAA", kind="financial", text="I bought it at nineteen. It is four.")
    assert led.videos_since_last() == 0 and not led.due()

    led.note("BBB")
    assert led.videos_since_last() == 1 and not led.due()
    led.note("CCC")
    assert led.videos_since_last() == 2 and led.due()

    assert [c.ticker for c in led.confessions()] == ["AAA"]
    assert len(led.entries()) == 3


def test_the_same_admission_cannot_be_told_twice(tmp_path):
    """Not the same wording — the same STORY, with the nouns moved.

    "A repetition rule someone has to remember will fail; a ledger makes it
    impossible."
    """
    led = _ledger(tmp_path)
    led.note("AAA", kind="financial",
             text="I bought it at nineteen. It is four. I have had a lot of "
                  "time to think about that.")

    retold = ("I paid nineteen for it and it is four now. I have had a lot of "
              "time to think about that one.")
    assert [c.ticker for c in led.repeats(retold)] == ["AAA"]

    fresh = ("There are several other things people use to predict this that I "
             "genuinely do not understand.")
    assert led.repeats(fresh) == []


def test_the_six_kinds_are_the_only_kinds():
    from pipeline.models import ScriptConfession
    from pipeline.standing import CONFESSION_KINDS

    assert len(CONFESSION_KINDS) == 6
    assert ScriptConfession(kind="Epistemic", text="x").kind == "epistemic"
    with pytest.raises(Exception):
        ScriptConfession(kind="sad", text="x")
