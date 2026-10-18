"""Voice bible v3: what the writer is handed, checked for what it must say."""

from __future__ import annotations

import difflib
import re

from pipeline import writing_files

ROOT_BIBLE = "voice_bible.md"


def _bible(settings) -> str:
    return (settings.assets_dir / ROOT_BIBLE).read_text(encoding="utf-8")


def test_it_is_v3(settings):
    assert _bible(settings).splitlines()[0].strip() == "# Dennis — voice bible v3"


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
