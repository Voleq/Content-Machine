"""A5: how a word is said to the voice, and only to the voice."""

from pipeline.models import WordTimestamp
from pipeline.pronounce import (Rule, add_rule, apply_rules, load_rules,
                                remove_rule, rules_hitting, shift_spans,
                                undo_rules)

RULES = [Rule("EBITDA", "ee bit dah"), Rule("10-K", "ten K")]


def _words(text, t=0.0):
    import re

    out = []
    for i, m in enumerate(re.finditer(r"\S+", text)):
        out.append(WordTimestamp(word=m.group(0), start=t + i, end=t + i + 0.8,
                                 char_start=m.start(), char_end=m.end()))
    return out


def test_apply_and_undo_merge_one_word():
    src = "Look at EBITDA in the 10-K today."
    said, edits = apply_rules(src, RULES)
    assert said == "Look at ee bit dah in the ten K today."
    back = undo_rules(_words(said), edits, src)
    assert [w.word for w in back] == ["Look", "at", "EBITDA", "in", "the",
                                      "10-K", "today."]
    ebitda = back[2]
    assert (ebitda.start, ebitda.end) == (2.0, 4.8), "first start, last end"
    for w in back:
        assert src[w.char_start:w.char_end] == w.word


def test_word_with_a_suffix_keeps_it():
    src = "The EBITDA's fine."
    said, edits = apply_rules(src, [Rule("EBITDA", "ee-bit-dah")])
    assert said == "The ee-bit-dah's fine."
    back = undo_rules(_words(said), edits, src)
    assert [w.word for w in back] == ["The", "EBITDA's", "fine."]


def test_a_word_in_brackets_or_quotes_is_written_back():
    """The spoken form inside punctuation on both sides came back as the
    caption's word: "(ee-bit-dah)" in the captions and the transcript."""
    src = "Their (EBITDA) fell, and “EBITDA” and (EBITDA) again."
    rules = [Rule("EBITDA", "ee-bit-dah")]
    said, edits = apply_rules(src, rules)
    back = undo_rules(_words(said), edits, src)
    assert [w.word for w in back] == ["Their", "(EBITDA)", "fell,", "and",
                                      "“EBITDA”", "and", "(EBITDA)", "again."]
    for w in back:
        assert src[w.char_start:w.char_end] == w.word
    said, edits = apply_rules("A (10-K) here.", RULES)
    back = undo_rules(_words(said), edits, "A (10-K) here.")
    assert [w.word for w in back] == ["A", "(10-K)", "here."]


def test_protected_span_untouched():
    src = "EBITDA [EBITDA] EBITDA"
    said, edits = apply_rules(src, RULES, protect=[(7, 15)])
    assert said == "ee bit dah [EBITDA] ee bit dah"
    assert shift_spans([(7, 15)], edits) == [(11, 19)]
    assert said[11:19] == "[EBITDA]"


def test_case_and_whole_word():
    said, edits = apply_rules("ebitda EBITDAX EBITDA.", RULES)
    assert said == "ebitda EBITDAX ee bit dah."
    assert len(edits) == 1


def test_rules_hitting():
    assert rules_hitting("only the 10-K here", RULES) == [RULES[1]]
    assert rules_hitting("nothing", RULES) == []


def test_add_remove_rule_roundtrip(settings):
    shipped = load_rules(settings)
    assert Rule("EBITDA", "ee-bit-dah") in shipped
    add_rule(settings, "EXMPL", "example corp")
    add_rule(settings, "EXMPL", "ex ample")          # replaces, never stacks
    rules = load_rules(settings)
    assert [r for r in rules if r.word == "EXMPL"] == [Rule("EXMPL", "ex ample")]
    assert remove_rule(settings, "EXMPL")
    assert not remove_rule(settings, "EXMPL")
    assert all(r.word != "EXMPL" for r in load_rules(settings))
    assert Rule("EBITDA", "ee-bit-dah") in load_rules(settings)
