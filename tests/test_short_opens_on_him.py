"""V4: a short opens on him, close up, with its big number.

The first frame of a short used to be the hook card: type on paper, no
number at size and nobody in it. A short now opens on a cold shot of at most
`OPEN_ON_HIM_S`: Dennis in close-up in his room, with the video's one number
on a strip of paper, set final from frame one. The hook card follows as it
always did.
"""

from __future__ import annotations

import json

import pytest

from pipeline.render_short import host_shots, opening_number
from pipeline.shots import (MIN_SHOT_S, OPEN_MIN_S, OPEN_ON_HIM_S,
                            TemplateError, apply_order, load_format,
                            order_names, parse_format, resolve_spans)


class FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word, self.start, self.end = word, start, end


def _words(duration: float = 60.0, n: int = 200) -> list[FakeWord]:
    step = duration / n
    return [FakeWord(f"w{i}", i * step, (i + 1) * step) for i in range(n)]


def _said(text: str, step: float = 0.3) -> list[FakeWord]:
    return [FakeWord(w, i * step, (i + 1) * step - 0.02)
            for i, w in enumerate(text.split())]


@pytest.mark.parametrize("name", ["short", "earnings", "macro"])
def test_every_vertical_format_opens_on_him(name):
    fmt = load_format(name)
    assert fmt.opener is not None
    assert fmt.opener.host is not None
    assert fmt.opener.host.pose == "host/close-up"
    assert fmt.opener.plate == "room/talk"
    # Big type and the caption band never share a shot.
    assert fmt.opener.captions is False
    # He is not one of the beats a writer marks or an order moves.
    assert fmt.opener.anchor is None
    assert fmt.opener.id not in {sh.id for sh in fmt.shots}
    assert fmt.cut_shots[0] is fmt.opener
    for order in order_names(fmt):
        assert apply_order(fmt, order).opener is fmt.opener


@pytest.mark.parametrize("name", ["short", "earnings", "macro"])
def test_the_cut_opens_on_him_and_the_hook_follows(name):
    fmt = load_format(name)
    spans = resolve_spans(fmt, _words(), 60.0, {})
    first, second = spans[0], spans[1]
    assert first.shot is fmt.opener
    assert first.start == 0.0
    assert OPEN_MIN_S <= first.end <= OPEN_ON_HIM_S + 1e-6
    assert second.shot.id == fmt.shots[0].id
    assert second.start == pytest.approx(first.end)
    assert spans[-1].end == pytest.approx(60.0)


def test_he_hands_over_on_the_end_of_a_word():
    fmt = load_format("short")
    words = _said("EXMPL is up twenty nine percent today and the business "
                  "is not up at all " + " ".join(f"w{i}" for i in range(150)))
    spans = resolve_spans(fmt, words, 50.0, {})
    ends = {round(w.end, 3) for w in words}
    assert round(spans[0].end, 3) in ends
    assert spans[0].end <= OPEN_ON_HIM_S


def test_he_hands_over_at_the_end_of_a_short_first_sentence():
    fmt = load_format("short")
    words = _said("Up thirty. Nobody asked why the business is still flat "
                  + " ".join(f"w{i}" for i in range(150)), step=0.5)
    spans = resolve_spans(fmt, words, 80.0, {})
    # "Up thirty." ends at 0.98: the cut is the full stop, not 1.6 s.
    assert spans[0].end == pytest.approx(0.98)


def test_a_hook_too_short_to_share_keeps_the_old_opening():
    raw = json.loads(load_format("short").source.read_text(encoding="utf-8"))
    words = _words(9.0, 30)
    without = dict(raw)
    without.pop("opener")
    hook = resolve_spans(parse_format(without), words, 9.0, {})[0]
    # Ten shots in nine seconds: the hook gets too little to hold both a
    # cold shot and the card the first words are read over.
    assert hook.dur < OPEN_MIN_S + MIN_SHOT_S
    spans = resolve_spans(parse_format(raw), words, 9.0, {})
    assert spans[0].shot.id == "hook"
    assert spans[0].start == 0.0
    assert spans[0].end == pytest.approx(hook.end)


def test_host_shots_name_the_opener():
    fmt = load_format("short")
    assert host_shots(fmt) == (fmt.opener.id, "the-turn")


def test_an_opener_without_him_is_refused():
    raw = json.loads(load_format("short").source.read_text(encoding="utf-8"))
    raw["opener"] = dict(raw["opener"])
    raw["opener"].pop("host")
    with pytest.raises(TemplateError, match="opener"):
        parse_format(raw)


def test_an_opener_named_like_a_shot_is_refused():
    raw = json.loads(load_format("short").source.read_text(encoding="utf-8"))
    raw["opener"] = dict(raw["opener"], id="hook")
    with pytest.raises(TemplateError, match="hook"):
        parse_format(raw)


class _Resolver:
    def __init__(self, **got: str) -> None:
        self.got = got

    def text_for(self, src: str) -> str | None:
        return self.got.get(src)


@pytest.mark.parametrize("got,want", [
    ({"chart.move": "+29%", "compare.reported": "$1.02",
      "numbers.headline_figure": "-$15M"}, ("+29%", "move")),
    ({"compare.reported": "$1.02", "numbers.headline_figure": "-$15M"},
     ("$1.02", "print")),
    ({"numbers.headline_figure": "-$15M"}, ("-$15M", "payoff")),
    ({"script.ticker": "EXMPL"}, ("EXMPL", "ticker")),
    ({}, ("", "")),
])
def test_the_number_is_the_move_else_the_print_else_the_payoff(got, want):
    fmt = load_format("short")
    assert opening_number(fmt, _Resolver(**got)) == want
