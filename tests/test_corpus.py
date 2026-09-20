"""The script corpus: what it indexes, and what similarity means here."""

from __future__ import annotations

import json

from pipeline.corpus import (
    Corpus, Overlap, ScriptEntry, build_index, compare, jaccard, mask_data,
    sentences, shingles,
)


def _write_script(settings, ticker: str, workdate: str, narration: str,
                  fmt: str = "short") -> None:
    ws = settings.workspace_dir / ticker / workdate
    ws.mkdir(parents=True, exist_ok=True)
    key = "narration" if fmt == "long" else "audio_script"
    (ws / f"script_{fmt}.json").write_text(
        json.dumps({"ticker": ticker, "format": fmt, key: narration}),
        encoding="utf-8")


# --------------------------------------------------------------------- shape


def test_the_index_walks_every_workspace(settings):
    _write_script(settings, "AAPL", "2026-09-01", "One. Two. Three.")
    _write_script(settings, "MSFT", "2026-09-02", "Four. Five.", fmt="long")

    entries = build_index(settings)

    assert [e.key for e in entries] == [
        "AAPL/2026-09-01/short", "MSFT/2026-09-02/long"]
    assert entries[0].hook == "One."
    assert entries[1].fmt == "long"


def test_an_empty_script_is_not_indexed(settings):
    _write_script(settings, "AAPL", "2026-09-01", "   ")
    assert build_index(settings) == []


def test_a_missing_workspace_dir_is_an_empty_corpus(settings):
    # Nothing has ever been made. That is a state, not a failure.
    assert build_index(settings) == []


def test_the_index_is_cached_and_refreshes(settings):
    _write_script(settings, "AAPL", "2026-09-01", "One. Two.")
    corpus = Corpus(settings)
    assert len(corpus) == 1
    assert (settings.state_dir / "script_corpus.json").exists()

    _write_script(settings, "MSFT", "2026-09-02", "Three.")
    assert len(Corpus(settings)) == 1, "the cache is the point of the cache"
    assert len(Corpus(settings, fresh=True)) == 2


def test_a_cache_written_by_an_older_shape_is_rebuilt(settings):
    _write_script(settings, "AAPL", "2026-09-01", "One.")
    (settings.state_dir / "script_corpus.json").write_text(
        json.dumps([{"gone": "field"}]), encoding="utf-8")

    assert len(Corpus(settings)) == 1


# ------------------------------------------------------------------- masking


def test_masking_removes_the_data_and_keeps_the_scaffolding():
    masked = mask_data("AAPL earned 4.2bn, up 31% from 3.2bn.")
    assert "4.2bn" not in masked
    assert "31%" not in masked
    assert "AAPL" not in masked
    assert "earned" in masked and "up" in masked and "from" in masked


def test_two_videos_built_the_same_way_look_the_same(settings):
    # The whole reason the comparison masks: different company, different
    # numbers, identical scaffolding. Raw text would call these unrelated.
    a = ("AAPL fell 31% this quarter and the market says it is cheap. "
         "But look at what the filings actually show.")
    b = ("MSFT fell 12% this quarter and the market says it is cheap. "
         "But look at what the filings actually show.")

    assert jaccard(shingles(a), shingles(b)) > 0.8


def test_two_genuinely_different_scripts_do_not_collide():
    a = "The balance sheet is where this argument has to start."
    b = "Management spent the whole call talking about a product nobody asked for."

    assert jaccard(shingles(a), shingles(b)) < 0.1


def test_jaccard_of_an_empty_side_is_zero():
    assert jaccard(set(), {("a", "b")}) == 0.0
    assert jaccard({("a", "b")}, set()) == 0.0


def test_a_script_shorter_than_the_window_still_shingles():
    assert shingles("Two words") == {("two", "words")}


# ---------------------------------------------------------------- comparison


def test_compare_reports_the_repeated_run_in_words():
    prior = ScriptEntry(
        ticker="MSFT", workdate="2026-09-01", fmt="short",
        narration="the market says it is cheap but the filings disagree here")
    mine = "the market says it is cheap but the filings disagree here too"

    overlaps = compare(mine, [prior])

    assert overlaps[0].phrasing > 0.5
    assert overlaps[0].percent > 50
    # The writer gets a phrase back, not a tuple of five-word windows.
    assert "the market says it is cheap" in overlaps[0].shared[0]


def test_compare_orders_by_similarity():
    close = ScriptEntry(ticker="A", workdate="2026-09-01", fmt="short",
                        narration="one two three four five six seven")
    far = ScriptEntry(ticker="B", workdate="2026-09-02", fmt="short",
                      narration="nothing here resembles the other script")

    out = compare("one two three four five six seven eight", [far, close])

    assert [o.entry.ticker for o in out] == ["A", "B"]


def test_an_overlap_with_nothing_shared_reports_no_runs():
    other = ScriptEntry(ticker="B", workdate="2026-09-02", fmt="short",
                        narration="entirely unrelated wording throughout")
    assert compare("a completely separate set of words", [other])[0].shared == []


# -------------------------------------------------------------------- search


def test_search_finds_the_sentence_and_the_script_it_is_in(settings):
    _write_script(settings, "AAPL", "2026-09-01",
                  "A line worth keeping. Another line entirely.")
    _write_script(settings, "MSFT", "2026-09-02", "Something else again.")

    hits = Corpus(settings).search("worth keeping")

    assert len(hits) == 1
    entry, said = hits[0]
    assert entry.ticker == "AAPL"
    assert said == "A line worth keeping."


def test_search_ignores_case_and_spacing(settings):
    _write_script(settings, "AAPL", "2026-09-01", "A line   worth keeping.")
    assert Corpus(settings).search("WORTH  KEEPING")


def test_search_for_nothing_returns_nothing(settings):
    _write_script(settings, "AAPL", "2026-09-01", "A line.")
    assert Corpus(settings).search("   ") == []


def test_recent_excludes_the_script_being_checked(settings):
    _write_script(settings, "AAPL", "2026-09-01", "One.")
    _write_script(settings, "MSFT", "2026-09-02", "Two.")

    corpus = Corpus(settings)
    rows = corpus.recent(10, fmt="short", exclude="MSFT/2026-09-02/short")

    assert [e.ticker for e in rows] == ["AAPL"]


def test_sentences_keep_their_terminators():
    # The terminator is data, not punctuation to be tidied away: a question
    # mark is what the delivery linter reads as a turn.
    assert sentences("One. Two! Three?\nFour") == ["One.", "Two!", "Three?",
                                                   "Four"]


def test_a_closing_quote_stays_with_its_sentence():
    assert sentences('He said "go." Then he left.') == ['He said "go."',
                                                        "Then he left."]
