"""The voice bible: what the writer is handed, checked for what it must say."""

from __future__ import annotations

import difflib
import re

from pipeline import writing_files

ROOT_BIBLE = "voice_bible.md"


def _bible(settings) -> str:
    return (settings.assets_dir / ROOT_BIBLE).read_text(encoding="utf-8")


def test_it_says_how_things_are_not_how_they_were(settings):
    """His note, 3 Nov 2026: "the prompts mention that v3 was how it was, v4
    is how it is and so on, this fact being hard to catch by the llm". The
    writer reads the rules as they stand, with no version history."""
    text = _bible(settings)
    assert text.splitlines()[0].strip() == "# Dennis — voice bible"
    assert "What changed" not in text
    assert not re.search(r"\bv[2-9]\b", text), re.search(r".{40}\bv[2-9]\b.{40}", text)


def test_benjamins_bits_come_first_with_how_to_use_each(settings):
    """3 Nov 2026: his lines "higher in the recommended examples", each with
    what to do with it, in place of the recurring-cast section. The noose
    bit and the slur-named one stay out until he says otherwise."""
    text = _bible(settings)
    bits = text[text.index("## Benjamin's bits"):text.index("## 1 ·")]
    rows = [l for l in bits.splitlines() if l.startswith("- **")]
    assert len(rows) >= 30
    assert all("*Dennis:*" in r for r in rows)
    low = text.lower()
    assert "noose" not in low and "retard" not in low
    assert "recurring cast" not in low


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
    assert "every minute or two" in para and "at least three" in para
    assert "never padded" in para


def test_fewer_self_owns_and_the_dark_detour(settings):
    """RDDT long, 1 Nov 2026: ten self-owns in one long, none of them funny,
    and none of the Laredo kind he asked for."""
    text = _bible(settings)
    five = text[text.index("## 5"):text.index("## 6")]
    assert "At most two in a long" in five and "none is fine" in five
    two = text[text.index("## 2"):text.index("## 3")]
    assert "the dark detour" in two and "at least three" in two
    four = text[text.index("## 4"):text.index("## 5")]
    assert "at most twice in a long" in four


def test_a_joke_that_teaches_nothing_is_not_cut_for_it(settings):
    """v3's test cut every joke that taught nothing extra, which is most of
    the good ones."""
    text = _bible(settings)
    test = text[text.index("### The test that governs all of them"):]
    test = test[:test.index("## 4")]
    assert "If it teaches exactly the same thing, cut it" not in test
    assert "being funny is its job" in test


def test_no_self_own_in_a_short_and_rarely_the_account(settings):
    """3 Nov 2026: no jokes about his persona in shorts; self-owns "not every
    video", at most two in a long; his empty account about one video in
    twenty; no job-centre puns; new relatable material."""
    text = _bible(settings)
    para = text[text.index("## 5"):text.index("## 6")]
    assert "A short carries none" in para
    assert "self-own is in every video" not in para
    assert "one video in twenty" in para
    assert "Never a job-centre joke" in para
    assert "sports" in para
    assert "one long in three" in para.lower()
    assert "job centre" not in text.lower()


def test_the_bagholder_and_the_bad_company_are_moves(settings):
    text = _bible(settings)
    three = text[text.index("## 3"):text.index("## 4")]
    assert "**The bagholder, specifically.**" in three
    assert "forklift certification lunch break" in three
    assert "salvage-title Maserati" in three
    assert "**The bad company, trashed properly.**" in three


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


def test_swearing_is_earned_not_budgeted(settings):
    """3 Nov 2026: "Swear only if it is necessary, the situation is so absurd
    that it merits a swear"."""
    text = _bible(settings)
    para = text[text.lower().index("· swearing"):]
    assert "absurd enough to earn it" in para
    assert "Use the budget" not in text and "no budget" in para


def test_no_style_reference_is_in_the_bible(settings):
    """Benjamin's lines are a style reference, never an example to copy."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", _bible(settings))
                 if len(s.split()) >= 6]
    for ref in writing_files.list_lines(settings, "style_references"):
        a = ref.lower().split()
        for s in sentences:
            ratio = difflib.SequenceMatcher(None, a, s.lower().split()).ratio()
            assert ratio < 0.75, (ref, s)
