"""S11: opener kinds, read off the words, rotated in the prompt."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline import hook_types as ht


@pytest.mark.parametrize("text,kind", [
    ("Ninety-seven million of stock comp on sixty million of profit.", "number"),
    ("Why would a company with no debt borrow two billion?", "question"),
    ("Not software. Not chips. Eyeliner.", "withheld"),
    ("A business that grew four times in five years, selling to teenagers.",
     "withheld"),
    ("I bought this at nineteen and it is four.", "confession"),
    ("Revenue doubled, but the stock halved.", "contradiction"),
    ("Welcome back to the channel.", "other"),
    ("", "other"),
])
def test_classify(text, kind):
    assert ht.classify_hook(text) == kind


def test_pick_least_recent():
    recent = ["number", "question", "withheld", "number", "contradiction"]
    assert ht.pick_hook_type(recent) == "confession"
    assert ht.pick_hook_type(recent, allow_confession=False) == "question"
    assert ht.pick_hook_type([]) == "number"


def test_block_names_last_types_and_pick(settings, monkeypatch):
    monkeypatch.setattr(ht, "recent_hook_types",
                        lambda s, fmt, n=6: ["number", "number"])
    text = ht.hook_type_block(settings, "short")
    assert "number, number" in text and "**question**" in text


def test_bench_by_type_means():
    bench = [SimpleNamespace(text="Why did it fall?", hold=0.8),
             SimpleNamespace(text="Why is it up?", hold=0.6),
             SimpleNamespace(text="Forty percent down.", hold=0.5)]
    rows = ht.bench_by_type(bench)
    assert rows[0][0] == "question" and rows[0][2] == 2
    assert abs(rows[0][1] - 0.7) < 1e-9
