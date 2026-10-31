"""Voice bible v4: what the writer is handed, checked for what it must say."""

from __future__ import annotations

import difflib
import re

from pipeline import writing_files

ROOT_BIBLE = "voice_bible.md"


def _bible(settings) -> str:
    return (settings.assets_dir / ROOT_BIBLE).read_text(encoding="utf-8")


def test_it_is_v4(settings):
    assert _bible(settings).splitlines()[0].strip() == "# Dennis — voice bible v4"


def test_it_names_the_register_he_asked_for(settings):
    """30 Oct 2026: "the benjamin style that i want to approach is nowhere to
    be found". The writer is told which register, by name, at the top."""
    head = _bible(settings)[:2000]
    assert "Benjamin" in head and "@benjjjaamiinn" in head


def test_density_is_a_floor_not_a_ceiling(settings):
    """v3 called density "a ceiling, not a quota" and "deliberately lower
    than a comedy channel"; Gemini read it and wrote six jokes in a long."""
    text = _bible(settings)
    para = text[text.index("## 7"):text.index("## 8")]
    low = para.lower()
    assert "a floor, not a ceiling" in low
    assert "ceiling, not a quota" not in low
    assert "lower density than a comedy channel" not in low
    assert "a joke a minute" in para and "at least three" in para


def test_a_joke_that_teaches_nothing_is_not_cut_for_it(settings):
    """v3's test cut every joke that taught nothing extra, which is most of
    the good ones."""
    text = _bible(settings)
    test = text[text.index("### The test that governs all of them"):]
    test = test[:test.index("## 4")]
    assert "If it teaches exactly the same thing, cut it" not in test
    assert "being funny is its job" in test


def test_the_self_own_is_every_video_and_the_confession_is_not(settings):
    text = _bible(settings)
    para = text[text.index("## 5"):text.index("## 6")]
    assert "self-own is in every video, the short included" in para
    assert "one video in three" in para.lower()


def test_benjamins_moves_are_named(settings):
    text = _bible(settings).lower()
    for move in ("the wrong last item", "the data he does not have",
                 "the quote nobody said", "the self-own on credibility",
                 "the crowd, roasted as a crowd",
                 "the swear on the plain restatement"):
        assert move in text, move


def test_it_carries_the_new_sections(settings):
    text = _bible(settings).lower()
    for heading in ("his story", "recurring bits", "swearing"):
        assert heading in text, heading


def test_the_swearing_numbers_are_the_agreed_ones(settings):
    text = _bible(settings)
    para = text[text.lower().index("· swearing"):][:1200]
    assert "four" in para and "one" in para
    assert "title" in para and "thumbnail" in para


def test_the_new_cast_is_listed(settings):
    text = _bible(settings).lower()
    for who in ("tiktok guru", "signal discord", "chart-lines guy",
                "comment-section", "macro doom guy"):
        assert who in text, who


def test_no_style_reference_is_in_the_bible(settings):
    """Benjamin's lines are a style reference, never an example to copy."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", _bible(settings))
                 if len(s.split()) >= 6]
    for ref in writing_files.list_lines(settings, "style_references"):
        a = ref.lower().split()
        for s in sentences:
            ratio = difflib.SequenceMatcher(None, a, s.lower().split()).ratio()
            assert ratio < 0.75, (ref, s)
