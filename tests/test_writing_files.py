"""The writing lists the operator edits: shipped defaults, his copy wins."""

from __future__ import annotations

import pytest

from pipeline import writing_files as wf


def test_state_copy_wins_over_asset(settings):
    shipped = wf.read_file(settings, "ai_phrases")
    assert "here's the thing" in shipped.lower()
    wf.write_file(settings, "ai_phrases", "only this\n")
    assert wf.read_file(settings, "ai_phrases") == "only this\n"


def test_write_goes_to_state_only(settings):
    asset = settings.assets_dir / "writing" / wf.WRITING_FILES["dennis_story"]
    before = asset.read_bytes()
    out = wf.write_file(settings, "dennis_story", "Dennis, 25.\n")
    assert out.parent == settings.state_dir / "writing"
    assert asset.read_bytes() == before


def test_reset_removes_state_copy(settings):
    wf.write_file(settings, "ai_phrases", "x\n")
    assert wf.reset(settings, "ai_phrases") is True
    assert "let that sink in" in wf.read_file(settings, "ai_phrases")
    assert wf.reset(settings, "ai_phrases") is False


def test_list_lines_drops_comments_and_blanks(settings):
    wf.write_file(settings, "ai_phrases", "# a note\n\n  delve  \nmoreover\n")
    assert wf.list_lines(settings, "ai_phrases") == ["delve", "moreover"]


def test_phrase_patterns_plain_and_regex(settings):
    wf.write_file(settings, "ai_phrases",
                  "here's the thing\nre: \\bdelv\\w*\n")
    pats = dict(wf.phrase_patterns(settings))
    assert pats["here's the thing"].search("Here's the thing: it fell.")
    assert pats[r"\bdelv\w*"].search("we are delving into it")
    assert not pats["here's the thing"].search("there's the thingamajig")


def test_bad_regex_line_is_skipped(settings, caplog):
    wf.write_file(settings, "ai_phrases", "re: (unclosed\ndelve\n")
    pats = wf.phrase_patterns(settings)
    assert [p for p, _ in pats] == ["delve"]


def test_unknown_name_raises_keyerror(settings):
    with pytest.raises(KeyError):
        wf.read_file(settings, "nope")
