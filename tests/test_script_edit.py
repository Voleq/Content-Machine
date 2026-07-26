"""In-chat script revision (P3.1c).

Two properties carry the whole feature, and both are about not losing work:

* an edit that does not parse **never lands** — the workspace keeps the script
  it had, and the operator gets the parser's complaint; and
* every revision that does land re-runs the gates, re-prices, and **drops the
  approval**, so nothing can be rendered from a version nobody read.
"""

from __future__ import annotations

import pytest

from pipeline.script_edit import (
    EditError,
    diff_lines,
    edit_lines,
    numbered,
    parse_target,
    replace_text,
)

CHAT = 4242

SCRIPT = (
    "EXMPL is cheap and hated, which is usually the same sentence.\n"
    "Revenue grew four point seven percent last year.\n"
    "[CHART: revenue]\n"
    "That is not a growth company. That is a utility with a story.\n"
    "See you at the next filing.\n"
)


# --------------------------------------------------------------------------
# Addressing lines the way the operator sees them.
# --------------------------------------------------------------------------


def test_numbering_matches_what_edit_expects():
    """`/script` prints these numbers and `/edit N` consumes them — if they
    disagree the operator edits the wrong line."""
    listing = numbered(SCRIPT)
    rows = listing.splitlines()
    assert rows[0].startswith("  1 | EXMPL is cheap")
    assert rows[2].startswith("  3 | [CHART: revenue]")
    # numbering counts every line, blanks included
    assert len(rows) == len(SCRIPT.splitlines())


def test_a_range_and_a_single_line_both_parse():
    assert parse_target("3", 5) == (3, 3)
    assert parse_target("2-4", 5) == (2, 4)
    assert parse_target("2..4", 5) == (2, 4)


def test_a_line_past_the_end_is_refused_with_the_real_count():
    with pytest.raises(EditError) as e:
        parse_target("99", 5)
    assert "5 lines" in str(e.value)
    assert "/script" in str(e.value)


def test_nonsense_targets_are_refused_with_the_usage():
    for bad in ("banana", "", "-3", "4-2"):
        with pytest.raises(EditError):
            parse_target(bad, 5)


# --------------------------------------------------------------------------
# The edits themselves.
# --------------------------------------------------------------------------


def test_replacing_one_line_leaves_every_other_byte_alone():
    out = edit_lines(SCRIPT, "2", "Revenue grew four point six percent last year.")
    lines = out.text.splitlines()
    assert lines[1] == "Revenue grew four point six percent last year."
    assert lines[0] == SCRIPT.splitlines()[0]
    assert lines[2] == "[CHART: revenue]"
    assert out.text.endswith("\n"), "the trailing newline was dropped"
    assert out.changed_lines == [2]


def test_a_range_collapses_to_the_replacement():
    out = edit_lines(SCRIPT, "2-4", "The numbers are flat and the story isn't.")
    lines = out.text.splitlines()
    assert lines == [SCRIPT.splitlines()[0],
                     "The numbers are flat and the story isn't.",
                     "See you at the next filing."]
    assert "2–4" in out.summary


def test_no_replacement_text_deletes_the_line():
    out = edit_lines(SCRIPT, "3", "")
    assert "[CHART: revenue]" not in out.text
    assert len(out.text.splitlines()) == 4
    assert "deleted" in out.summary


def test_a_multi_line_replacement_becomes_multiple_lines():
    out = edit_lines(SCRIPT, "4", "First half.\nSecond half.")
    lines = out.text.splitlines()
    assert lines[3] == "First half."
    assert lines[4] == "Second half."
    assert out.changed_lines == [4, 5]


def test_re_sending_the_same_text_is_called_out_not_silently_applied():
    with pytest.raises(EditError) as e:
        edit_lines(SCRIPT, "3", "[CHART: revenue]")
    assert "already reads" in str(e.value)


# --------------------------------------------------------------------------
# Find and replace — what you reach for when a figure is wrong.
# --------------------------------------------------------------------------


def test_replace_fixes_the_first_occurrence():
    out = replace_text(SCRIPT, "four point seven => four point six")
    assert "four point six percent" in out.text
    assert "four point seven" not in out.text


def test_replace_warns_when_the_text_appears_more_than_once():
    """Editing the first of several is how the wrong number survives in the
    second half of the script."""
    doubled = SCRIPT + "Again: four point seven percent.\n"
    out = replace_text(doubled, "four point seven => four point six")
    assert "appears 2 times" in out.summary
    assert out.text.count("four point seven") == 1, "should edit only the first"


def test_replace_all_takes_every_occurrence():
    doubled = SCRIPT + "Again: four point seven percent.\n"
    out = replace_text(doubled, "all: four point seven => four point six")
    assert "four point seven" not in out.text
    assert out.text.count("four point six") == 2
    assert "2 occurrences" in out.summary


def test_replacing_text_that_is_not_there_is_refused():
    with pytest.raises(EditError) as e:
        replace_text(SCRIPT, "nine point nine => eight")
    assert "does not appear" in str(e.value)


def test_a_malformed_replace_gets_the_usage():
    with pytest.raises(EditError) as e:
        replace_text(SCRIPT, "just some text with no arrow")
    assert "=>" in str(e.value)


def test_an_empty_replacement_deletes_the_phrase():
    out = replace_text(SCRIPT, "which is usually the same sentence. =>")
    assert "same sentence" not in out.text
    assert "deleted" in out.summary


def test_the_diff_shows_the_line_that_moved():
    out = edit_lines(SCRIPT, "2", "Revenue grew four point six percent last year.")
    d = diff_lines(SCRIPT, out.text)
    assert "−" in d and "+" in d
    assert "four point seven" in d
    assert "four point six" in d


# --------------------------------------------------------------------------
# The bot flow: revisions land only if they parse, and reset the approval.
# --------------------------------------------------------------------------


@pytest.fixture()
def core_with_long(settings, long_valid_text):
    """A workspace holding a parsed, approved LONG."""
    from bot.handlers import BotCore
    from pipeline.company_data import load_company_data  # noqa: F401
    import shutil
    from pathlib import Path

    core = BotCore(settings)
    core.new_ticker(CHAT, "EXMPL")
    ws = core.context.get(CHAT)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    shutil.copy(fixtures / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    core.intake_script(CHAT, long_valid_text)
    script = ws.load_long()
    ws.approve("long", script.content_sha(), "the report they read")
    assert ws.is_approved("long")
    return core, ws


def test_the_listing_reports_the_state_the_operator_needs(core_with_long):
    core, ws = core_with_long
    reply = core.script_listing(CHAT)
    assert "EXMPL LONG" in reply.text
    assert "approved" in reply.text
    assert "/edit" in reply.text and "/replace" in reply.text


def test_an_edit_reruns_the_gates_and_reprices(core_with_long):
    core, ws = core_with_long
    raw = ws.raw_script("long")
    first = raw.splitlines()[0]

    reply = core.edit_script(CHAT, ["1", "A completely different opening line."])
    assert "replaced line 1" in reply.text
    # the cost report came back with it — that is the re-pricing
    assert "TTS" in reply.text or "chars" in reply.text
    assert ws.raw_script("long").splitlines()[0] != first


def test_an_edit_withdraws_the_approval(core_with_long):
    """Approval is pinned to the script's hash; an edit changes the hash, so
    the render gate can never run on text nobody approved."""
    core, ws = core_with_long
    core.edit_script(CHAT, ["1", "A completely different opening line."])
    assert not ws.is_approved("long")


def test_an_edit_that_breaks_the_parser_changes_nothing(core_with_long):
    """The invariant that makes this safe on an approved script.

    Naming the data vendor is a hard rejection (it would land in the captions),
    and it is exactly the sort of thing an operator types into a quick edit.
    """
    core, ws = core_with_long
    before = ws.raw_script("long")
    revs_before = ws.revision_count("long")

    reply = core.edit_script(CHAT, ["3", "According to Refinitiv, revenue fell."])

    assert "doesn't parse" in reply.text
    assert "unchanged" in reply.text
    assert ws.raw_script("long") == before, "a rejected edit corrupted the script"
    assert ws.revision_count("long") == revs_before


def test_an_edit_that_only_warns_still_lands(core_with_long):
    """An unknown tag key is a warning, not a rejection — the parser skips it.

    Worth pinning: the revision must land (with the warning surfaced) rather
    than being silently dropped as if it had failed.
    """
    core, ws = core_with_long
    reply = core.edit_script(CHAT, ["3", "[NONSENSE: not-a-real-tag] Still prose."])
    assert "replaced line 3" in reply.text
    assert "Still prose." in ws.raw_script("long")


def test_undo_steps_back_to_the_previous_revision(core_with_long):
    core, ws = core_with_long
    original = ws.raw_script("long")

    core.edit_script(CHAT, ["1", "First rewrite of the opening."])
    after_first = ws.raw_script("long")
    assert after_first != original

    reply = core.undo_edit(CHAT)
    assert "reverted" in reply.text
    assert ws.raw_script("long") == original


def test_undo_twice_goes_further_back_rather_than_toggling(core_with_long):
    core, ws = core_with_long
    original = ws.raw_script("long")
    core.edit_script(CHAT, ["1", "First rewrite."])
    core.edit_script(CHAT, ["2", "Second rewrite."])

    core.undo_edit(CHAT)
    after_one = ws.raw_script("long")
    assert "Second rewrite." not in after_one
    assert "First rewrite." in after_one

    core.undo_edit(CHAT)
    assert ws.raw_script("long") == original


def test_undo_with_nothing_to_undo_says_so(core_with_long):
    core, ws = core_with_long
    # burn the one revision the initial paste created, if any
    while ws.revision_count("long"):
        ws.pop_revision("long")
    reply = core.undo_edit(CHAT)
    assert "Nothing to undo" in reply.text


def test_a_full_repaste_still_works_as_the_other_route(core_with_long,
                                                      long_valid_text):
    """The brief asks for both: a targeted edit or a whole new paste."""
    core, ws = core_with_long
    edited = long_valid_text.replace("See you at the next filing.",
                                     "See you at the next filing. Probably.")
    reply = core.intake_script(CHAT, edited)
    assert "⛔" not in reply.text.splitlines()[0]
    assert "Probably." in ws.raw_script("long")
    assert not ws.is_approved("long")


def test_editing_with_no_script_on_file_is_refused(settings):
    from bot.handlers import BotCore

    core = BotCore(settings)
    core.new_ticker(CHAT, "EXMPL")
    assert "No script" in core.edit_script(CHAT, ["1", "text"]).text
    assert "No script" in core.script_listing(CHAT).text


def test_edit_without_arguments_explains_itself(core_with_long):
    core, _ = core_with_long
    reply = core.edit_script(CHAT, [])
    assert "/edit N" in reply.text


def test_replace_reaches_the_bot_the_same_way(core_with_long):
    core, ws = core_with_long
    raw = ws.raw_script("long")
    word = raw.split()[0]
    reply = core.edit_script(CHAT, [word, "=>", word], mode="replace")
    # replacing a word with itself is a no-op edit — the parser accepts it but
    # nothing should claim to have changed
    assert "replaced" in reply.text or "already" in reply.text
