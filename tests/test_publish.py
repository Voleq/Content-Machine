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
    body = out.read_text()
    assert body.startswith("1\n00:00:00,000 --> ")
    assert "-->" in body and body.count("-->") == 2
    assert "\n2\n" in body


def test_empty_words_make_an_empty_srt(tmp_path):
    assert write_srt([], tmp_path / "s.srt").read_text() == ""


def test_chapters_are_normalised_for_youtube():
    raw = "00:30 Cold open\n04:12 The numbers\n09:00 What you're paying for"
    got = normalise_chapters(raw)
    assert len(got) == 3
    # YouTube only renders chapters when the first is at 00:00
    assert got[0][0] == "00:00"
    assert got[1] == ("04:12", "The numbers")


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
