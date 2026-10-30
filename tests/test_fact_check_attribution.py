"""The fact-check against a real short it wrongly blocked (BA, 30 Oct 2026).

Four blocks on one earnings short, every one of them the check reading a
figure as the wrong line or the wrong period: the day's -10.7% as operating
income growth, a quarter's cash flow as a year's revenue, free cash flow
"burned" as a positive, and the reverse DCF's implied growth as EBITDA's.
Each test pins the true sentence passing AND a wrong one still caught, so the
check got narrower about what it reads, not blind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.gates import (
    TRUSTED_FILE,
    fact_check,
    finding_key,
    run_gates,
    trust_finding,
)
from pipeline.models import CompanyData

ROOT = Path(__file__).resolve().parents[1]
M = 1e6


@pytest.fixture()
def ba():
    """A Boeing-shaped workbook: six yearly columns and eight quarters."""
    return CompanyData(
        values={"company_name": "The Boeing Company", "ticker": "BA"},
        history_years=["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        history={
            "revenue": [62286 * M, 66608 * M, 77794 * M, 66517 * M, 89463 * M, 94913 * M],
            "operating_income": [-473 * M, -817 * M, 780 * M, -10000 * M, -5190 * M, 60 * M],
            "fcf": [-4396 * M, 2290 * M, 4433 * M, -14310 * M, -1877 * M, -357 * M],
            "ebitda": [2400 * M, 1668 * M, 3792 * M, -11748 * M, -4652 * M, 3200 * M],
            "diluted_shares": [588 * M, 595 * M, 606 * M, 647 * M, 762 * M, 788 * M],
            "total_debt": [58000 * M, 57000 * M, 52300 * M, 53900 * M, 47000 * M, 45000 * M],
        },
        quarter_labels=["Q1 FY24", "Q2 FY24", "Q3 FY24", "Q4 FY24",
                        "Q1 FY25", "Q2 FY25", "Q3 FY25", "Q4 FY25"],
        quarters={
            "revenue": [16.57e9, 16.87e9, 17.84e9, 15.24e9,
                        19.5e9, 22.75e9, 23.27e9, 24.19e9],
            "fcf": [-3.9e9, -4.3e9, -2.0e9, -4.1e9, -2.3e9, 0.2e9, -0.912e9, 0.332e9],
        },
    )


def _blocks(text, data, **kw):
    return [f for f in fact_check(text, data, ticker="BA", **kw)
            if f.severity == "block"]


# ------------------------------------------------------------ the day's move


def test_the_company_s_name_is_the_stock_moving(ba):
    hook = ("Boeing is down ten point seven percent today, with sixty million "
            "dollars of operating profit on ninety five billion of sales.")
    assert fact_check(hook, ba, ticker="BA") == []
    # the figures beside the move are still read
    wrong = _blocks(hook.replace("sixty million", "ninety million"), ba)
    assert len(wrong) == 1 and "operating income" in wrong[0].message


def test_a_percentage_said_with_today_is_the_price(ba):
    assert fact_check("Down ten point seven percent today, on sixty million "
                      "of operating profit.", ba) == []


# ------------------------------------------------------- a beat is a sentence


def test_his_short_passes_its_checks(settings, ba):
    from pipeline.parser_short import parse_short_script

    raw = (ROOT / "fixtures" / "scripts" / "short_ba_earnings.json").read_text("utf-8")
    script, _ = parse_short_script(raw, settings)
    report = run_gates(script, settings, data=ba, skeptic=False,
                       as_of="2026-10-29", format_name="earnings")
    blocks = [f.render() for f in report.findings
              if f.gate == "fact-check" and f.severity == "block"]
    assert blocks == []
    # The hook's figures are read now: they used to share a sentence with the
    # headline's "estimates" and were passed over as guidance.
    assert not any("guidance" in f.message and "Boeing" in f.excerpt
                   for f in report.findings)


def test_a_beat_mark_ends_a_sentence(ba):
    text = ("Sixty million of operating profit [BEAT: headline] Revenue "
            "missed, though quarterly cash flow hit three hundred thirty two "
            "million.")
    assert fact_check(text, ba) == []


# --------------------------------------------------- cash flow, said bare


def test_quarterly_cash_flow_is_a_quarter_s_cash_flow(ba):
    ok = ("Revenue missed estimates, though quarterly cash flow hit three "
          "hundred thirty two million.")
    assert fact_check(ok, ba) == []
    wrong = _blocks(ok.replace("three hundred thirty two", "seven hundred"), ba)
    assert len(wrong) == 1
    assert "quarterly cash flow" in wrong[0].message
    assert "Q4 FY25 332M" in wrong[0].message, wrong[0].message


# ------------------------------------------------------- the period it says


def test_a_quarter_is_never_held_to_a_year(ba):
    assert fact_check("Quarterly revenue was twenty four point one nine "
                      "billion.", ba) == []
    out = _blocks("Quarterly revenue was ninety five billion.", ba)
    assert len(out) == 1 and "quarterly revenue" in out[0].message
    out = _blocks("Annual revenue was twenty four point one nine billion.", ba)
    assert len(out) == 1 and "yearly revenue" in out[0].message


def test_a_quarter_s_growth_on_a_year_ago_is_a_true_claim(ba):
    # Q4 FY25 24.19B on Q4 FY24 15.24B is +58.7%
    assert fact_check("Quarterly revenue rose fifty nine percent year over "
                      "year.", ba) == []
    assert _blocks("Quarterly revenue rose ninety percent year over year.", ba)


def test_a_quarterly_figure_with_no_quarterly_row_is_listed_not_blocked(ba):
    unread: list = []
    assert fact_check("Quarterly total debt was forty five billion.", ba,
                      unchecked=unread) == []
    assert unread and "no quarterly total debt row" in unread[0][2]


# --------------------------------------------------------- the sign of a burn


def test_cash_burned_is_a_negative_figure(ba):
    assert fact_check("Free cash flow burned three fifty seven million.", ba) == []
    assert fact_check("Free cash flow was a three fifty seven million "
                      "outflow.", ba) == []
    assert _blocks("Free cash flow burned four fifty seven million.", ba)


def test_a_sign_flip_says_so(ba):
    out = _blocks("Free cash flow was three fifty seven million.", ba)
    assert len(out) == 1 and "the sign does not" in out[0].message


# ------------------------------------------------------ what the price implies


def test_implied_growth_is_not_ebitda_growth(ba):
    unread: list = []
    line = ("Debt fell, yet seventy times EBITDA assumes nine point four "
            "percent perpetual cash growth.")
    assert fact_check(line, ba, unchecked=unread) == []
    assert unread and "implies" in unread[0][2]


def test_a_percentage_names_its_own_subject(ba):
    assert fact_check("EBITDA covers a nine percent dividend yield.", ba) == []
    out = _blocks("Boeing printed forty percent revenue growth.", ba)
    assert len(out) == 1 and "revenue growth" in out[0].message


# ------------------------------------------------------------- a guess warns


def test_a_figure_whose_metric_is_in_another_clause_warns(ba):
    out = fact_check("Revenue missed estimates, though deliveries hit nine "
                     "hundred million.", ba)
    assert [f.severity for f in out] == ["warn"]
    assert "a guess" in out[0].message


def test_a_recital_is_still_checked_to_its_last_figure(ba):
    ok = "Revenue went sixty two billion, then sixty six, then seventy seven."
    assert fact_check(ok, ba) == []
    out = fact_check(ok.replace("seventy seven", "ninety nine"), ba)
    assert [f.severity for f in out] == ["block"]


def test_the_message_names_each_column(ba):
    out = _blocks("Free cash flow burned four fifty seven million.", ba)
    assert "FY21 -4.4B" in out[0].message and "LTM -357M" in out[0].message
    assert "4,396,000,000" not in out[0].message


# --------------------------------------------------------- letting one through


def test_a_block_he_lets_through_becomes_a_note(settings, ba, tmp_path):
    from types import SimpleNamespace

    script = SimpleNamespace(ticker="BA", audio_script=(
        "Free cash flow burned four fifty seven million."), events=[],
        inline_events=[], beat_marks=[], headlines=[], numbers=[])
    first = run_gates(script, settings, data=ba, skeptic=False,
                      workspace=tmp_path)
    block = next(f for f in first.findings
                 if f.gate == "fact-check" and f.severity == "block")
    trust_finding(tmp_path, finding_key(block.render()))
    assert json.loads((tmp_path / TRUSTED_FILE).read_text())
    again = run_gates(script, settings, data=ba, skeptic=False,
                      workspace=tmp_path)
    assert not [f for f in again.findings
                if f.gate == "fact-check" and f.severity == "block"]
    assert any(f.message.startswith("you let this through")
               for f in again.findings)
    # a changed sentence gets checked again
    script.audio_script = "Free cash flow burned five fifty seven million."
    third = run_gates(script, settings, data=ba, skeptic=False,
                      workspace=tmp_path)
    assert [f for f in third.findings
            if f.gate == "fact-check" and f.severity == "block"]


def test_the_bot_lets_a_block_through_and_checks_again(settings):
    """`/script trust KEY` from the Check step's button: the block is on the
    current report, it becomes a note, the rest still block, and a key that
    is not a current fact-check block is refused."""
    import shutil

    from bot.handlers import BotCore

    core = BotCore(settings)
    core.start_lane(7, "short", "EXMPL")
    ws = core.context.get(7)
    shutil.copy(ROOT / "fixtures" / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    s = json.loads((ROOT / "fixtures" / "scripts" / "short_ba_earnings.json")
                   .read_text("utf-8"))
    s["ticker"] = "EXMPL"      # Boeing's figures against Example Corp's sheet
    core.intake_script(7, json.dumps(s))

    def fact_blocks():
        rep = json.loads((ws.path / "report_short.json").read_text("utf-8"))
        return [t for t in rep["blocking"] if t.startswith("[fact-check]")]

    before = fact_blocks()
    assert len(before) >= 2
    reply = core.trust_fact(7, finding_key(before[0]))
    assert reply.text.startswith("✅ Let through")
    after = fact_blocks()
    assert len(after) == len(before) - 1 and before[0] not in after
    assert "⛔" in core.trust_fact(7, "0123456789").text
