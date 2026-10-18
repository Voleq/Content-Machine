"""The writing on his things (pipeline/room_writing.py)."""

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from pipeline import room_writing as rw

ROOT = Path(__file__).resolve().parents[1]


def _settings():
    return SimpleNamespace(assets_dir=ROOT / "assets")


def test_the_filings_follow_the_videos_date():
    oct26 = rw.filings("exmpl", dt.date(2026, 10, 18))
    assert oct26["spine15"] == "10-K '25" and oct26["spine10"] == "10-K '20"
    assert [oct26[f"spine2{j}"] for j in range(3)] == ["10-Q Q3 '25", "10-Q Q1 '26",
                                                       "10-Q Q2 '26"]
    assert "EXMPL" in oct26["deskstack-top"] and "FISCAL YEAR 2025" in oct26["filing"]
    # before the annual report is out the shelf ends a year earlier
    feb = rw.filings("exmpl", dt.date(2027, 2, 1))
    assert feb["spine15"] == "10-K '25"
    assert rw.filings("exmpl", dt.date(2028, 6, 1))["spine15"] == "10-K '27"


def test_the_sign_says_not_financial_advice_every_video():
    for ep, day in [(1, "2026-10-18"), (2, "2026-11-02"), (0, "2027-03-09")]:
        said = dict(rw.props(None, ticker="EXMPL", workdate=day, episode=ep,
                             settings=_settings()))
        assert said["cs"] == "NOT\nFINANCIAL\nADVICE"


def test_neighbouring_videos_take_different_lines():
    a = dict(rw.props(None, ticker="EXMPL", workdate="2026-10-18", episode=4,
                      settings=_settings()))
    b = dict(rw.props(None, ticker="EXMPL", workdate="2026-10-25", episode=5,
                      settings=_settings()))
    notes = lambda d: {d[f"note{i}"] for i in range(rw.NOTES)}
    cards = lambda d: {d[f"card{i}"] for i in range(rw.CARDS)}
    assert not notes(a) & notes(b) and not cards(a) & cards(b)


def test_the_model_writes_only_what_the_script_says():
    script = "Revenue grew 12% to $4.1 billion while debt doubled."
    answer = json.dumps({
        "notes": ["debt doubled", "up 40%", "buy the dip", "12%"],
        "cards": [{"head": "Revenue", "lines": ["$4.1 billion", "grew 12%"]},
                  {"head": "Debt", "lines": ["7x leverage"]}]})
    notes, cards = rw._parse(answer, script)
    assert notes == ["debt doubled", "12%"]       # a made-up number and advice refused
    assert cards == ["REVENUE\n$4.1 billion\ngrew 12%"]


def test_the_models_answer_is_kept_for_a_rerender(tmp_path, monkeypatch):
    calls = []

    def fake(text, ticker, settings):
        calls.append(text)
        return ["debt doubled"], []

    monkeypatch.setattr(rw, "from_script", fake)
    script = SimpleNamespace(narration="Debt doubled.")
    one = rw.props(script, ticker="X", workdate="2026-10-18", episode=3,
                   settings=_settings(), workspace=tmp_path)
    two = rw.props(script, ticker="X", workdate="2026-10-18", episode=3,
                   settings=_settings(), workspace=tmp_path)
    assert one == two and len(calls) == 1
    assert dict(one)["note0"] == "debt doubled"
