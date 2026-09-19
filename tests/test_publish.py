"""Subtitles and the upload package — free by-products of a finished render."""

from __future__ import annotations

from pipeline.models import WordTimestamp
from pipeline.publish import (
    build_package,
    group_cues,
    normalise_chapters,
    write_srt,
    _timestamp,
)


def w(word, start, end):
    return WordTimestamp(word=word, start=start, end=end, char_start=0, char_end=1)


def test_timestamps_are_srt_format():
    assert _timestamp(0) == "00:00:00,000"
    assert _timestamp(3661.5) == "01:01:01,500"
    assert _timestamp(-1) == "00:00:00,000"


def test_cues_break_on_sentences():
    words = [w("Revenue", 0.0, 0.4), w("fell.", 0.4, 0.8),
             w("Margins", 1.0, 1.4), w("fell", 1.4, 1.7), w("more.", 1.7, 2.0)]
    cues = group_cues(words)
    assert len(cues) == 2
    assert cues[0][2] == "Revenue fell."
    assert cues[1][2] == "Margins fell more."


def test_a_long_pause_ends_a_cue():
    words = [w("So", 0.0, 0.3), w("that", 0.3, 0.6),
             w("happened", 3.0, 3.6)]
    assert len(group_cues(words)) == 2


def test_cues_never_exceed_the_readable_length():
    words = [w(f"word{i}", i * 0.3, i * 0.3 + 0.25) for i in range(60)]
    for start, end, text in group_cues(words):
        assert max(len(line) for line in text.splitlines()) <= 42
        assert len(text.splitlines()) <= 2
        assert end > start


def test_srt_is_written_and_well_formed(tmp_path):
    words = [w("Revenue", 0.0, 0.4), w("fell.", 0.4, 0.8),
             w("Then", 1.2, 1.5), w("stopped.", 1.5, 2.0)]
    out = write_srt(words, tmp_path / "sub.srt")
    body = out.read_text(encoding="utf-8")
    assert body.startswith("1\n00:00:00,000 --> ")
    assert "-->" in body and body.count("-->") == 2
    assert "\n2\n" in body


def test_empty_words_make_an_empty_srt(tmp_path):
    assert write_srt([], tmp_path / "s.srt").read_text(encoding="utf-8") == ""


def test_chapters_are_normalised_for_youtube():
    raw = "00:30 Cold open\n04:12 The numbers\n09:00 What you're paying for"
    got = normalise_chapters(raw)
    assert len(got) == 3
    # YouTube only renders chapters when the first is at 00:00
    assert got[0][0] == "00:00"
    # A line with no `type |` is a title with no type. Nothing is guessed.
    assert got[1] == ("04:12", "The numbers", "")


def test_the_type_is_split_off_the_title():
    """The trailer's grammar is `type | Display Title`, and only the title
    belongs on screen.

    Taking everything after the timestamp put the internal slug in the chapter
    list YouTube renders — "00:00 cold-open | nobody cares anymore" — and made
    the same string the retention record's chapter name, which is what stopped
    `chapter_type_evidence` from ever aggregating anything.
    """
    raw = ("00:00 cold-open | nobody cares anymore\n"
           "04:12 the-numbers | five years of them\n"
           "09:00 Resigned close | see you at the next filing")
    got = normalise_chapters(raw)
    assert got[0] == ("00:00", "nobody cares anymore", "cold-open")
    assert got[1] == ("04:12", "five years of them", "the-numbers")
    # The type folds to the kit's spelling — the writer types the trailer by
    # hand, and "Resigned close" recorded against "resigned-close" is the same
    # chapter in two buckets, which is the defect the type exists to fix. The
    # title is left exactly as written.
    assert got[2] == ("09:00", "see you at the next filing", "resigned-close")


def test_a_pipe_with_nothing_on_one_side_is_not_a_type():
    """Better a title that reads oddly than a type invented out of a stray
    character."""
    assert normalise_chapters("00:00 | orphaned pipe")[0][2] == ""
    assert normalise_chapters("00:00 trailing pipe |")[0][2] == ""


def test_junk_lines_are_ignored():
    assert normalise_chapters("not a chapter\n\n=== CHAPTERS ===") == []


def test_package_carries_chapters_and_never_invents_claims(settings,
                                                           long_valid_text):
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    script.chapters = "00:00 Cold open\n02:00 The numbers\n05:00 The close"
    pkg = build_package(script, settings, runtime_min=14)

    assert pkg.ticker == "EXMPL"
    assert len(pkg.titles) == 3 and all(pkg.titles)
    assert "02:00 The numbers" in pkg.description
    assert settings.disclaimer_text in pkg.description
    assert "EXMPL" in pkg.tags
    assert pkg.pinned_comment
    # The package must not make a call the video doesn't. Note the boilerplate
    # legitimately says "no price targets" — it is the *claim* that is banned,
    # not the phrase.
    low = pkg.render_text().lower()
    for banned in ("price target of", "buy now", "guaranteed", "strong buy"):
        assert banned not in low
    assert "no price targets" in low


def test_no_cue_ever_loses_its_ending():
    """A subtitle file is a transcript. `_wrap` ended with `lines[:2]`, so a
    cue that wrapped past two lines had its tail DELETED — silently, in the
    one artefact whose job is to say what was said."""
    from pipeline.publish import _wrap

    text = " ".join(["word"] * 40)
    assert _wrap(text).replace("\n", " ").split() == text.split()
    assert "\n" not in _wrap("short enough")


def test_the_cue_splitter_is_what_keeps_a_subtitle_to_two_lines():
    """And it asks the wrapper rather than counting characters: 84 chars is
    two lines only when the words happen to break in the right places."""
    from pipeline.publish import MAX_LINE, group_cues

    # Words wide enough that three of them will not fit on two lines.
    wide = "x" * (MAX_LINE - 4)
    words = [w(wide, i * 0.3, i * 0.3 + 0.25) for i in range(9)]
    for _start, _end, text in group_cues(words):
        lines = text.splitlines()
        assert len(lines) <= 2, f"three lines on screen: {text!r}"
        assert max(len(ln) for ln in lines) <= MAX_LINE

    spoken = " ".join(t for _s, _e, t in group_cues(words)).split()
    assert spoken == [wide] * 9, "the splitter must not lose words either"


def test_a_chapter_past_the_end_of_the_video_is_dropped():
    """YouTube renders NO chapter list when one is out of range, so a beat
    cut after the trailer was written used to cost the whole list."""
    raw = ("00:00 cold-open | The setup\n"
           "05:00 numbers | What the numbers say\n"
           "20:00 close | The verdict")

    assert len(normalise_chapters(raw)) == 3, "no duration, no opinion"

    kept = normalise_chapters(raw, duration_s=600.0)
    assert [c[1] for c in kept] == ["The setup", "What the numbers say"]


def test_a_duration_of_zero_is_not_an_answer():
    """`_render_duration` returns 0.0 when it cannot measure the file, and
    that must not read as "every chapter is out of range"."""
    raw = "00:00 a | A\n01:00 b | B\n02:00 c | C"
    assert len(normalise_chapters(raw, duration_s=0.0)) == 3
