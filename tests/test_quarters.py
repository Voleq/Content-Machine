"""Quarterly data (O): the sheet, both comparisons, and the checking.

`templates/shots/earnings.json` is a complete 9:16 format whose first two
beats are `the-print` and `vs-expected`. Before the Quarters sheet existed
there was no quarterly data anywhere in the system, so the writer supplied
the print from its own training knowledge and `fact_check` — which only had
annual series to compare against — could not verify a word of it. An
earnings video was structurally unverifiable (O0).

Every test here asserts on the loaded data, the rendered prompt block or the
gate's verdict, never on the fact that a reader ran (X1).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from pipeline.company_data import load_company_data
from pipeline.models import CONSENSUS_FIELDS, QUARTER_FIELDS


# --------------------------------------------------------------------------
# O6.1 — the sheet is optional, and its absence changes nothing else.
# --------------------------------------------------------------------------


def test_a_workbook_with_no_quarters_sheet_loads_and_warns(workspace, caplog):
    """O6.1, the one that protects every existing ticker.

    Not one workbook in the wild has this sheet yet. If a missing sheet were
    anything but a warning, the annual flow would break for all of them.
    """
    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    assert "Quarters" in wb.sheetnames, "fixture setup: the sheet must exist"
    wb.remove(wb["Quarters"])
    wb.save(xlsx)
    wb.close()

    with caplog.at_level("WARNING"):
        data = load_company_data(workspace)

    assert data.quarters == {} and data.quarter_labels == []
    assert data.has_quarters is False
    assert data.available_quarter_metrics() == []
    assert any("Quarters" in r.message for r in caplog.records), \
        "a missing optional sheet is said out loud, not swallowed"

    # AND THE ANNUAL FLOW IS UNTOUCHED. This is the real assertion.
    assert data.has_history and len(data.history_years) == 6
    assert data.history["revenue"][-1] == 496_000_000
    assert data.available_chart_metrics()[:2] == ["revenue", "gross_profit"]
    assert data.has_valuation and data.has_peers and data.news


def test_the_annual_prompt_block_is_unchanged_by_the_new_sheet(workspace):
    """The quarterly table is its OWN payload entry (O5), so adding the
    sheet must not have altered `{{company_data}}` at all — otherwise every
    prompt for every ticker changed underneath the feature."""
    data = load_company_data(workspace)
    block = data.as_prompt_block()
    assert "[history" in block
    assert "[quarters" not in block, \
        "the quarters table belongs to {{quarters}}, not {{company_data}}"


def test_the_operator_template_carries_a_readable_quarters_sheet():
    """The sheet the operator actually refreshes.

    Its cells are CapIQ formulas, so there are no VALUES to read here —
    what has to hold is that the header parses into eight period columns and
    every `field_key` is one the reader recognises. A row key the model does
    not carry is dropped with a warning, which would make a column of the
    workbook silently invisible.
    """
    from pipeline.company_data import _read_quarters

    src = Path(__file__).resolve().parents[1] / "templates" / "dennis_data_template.xlsx"
    wb = load_workbook(src)
    assert "Quarters" in wb.sheetnames
    labels, rows = _read_quarters(wb["Quarters"])
    wb.close()

    assert len(labels) == 8, f"expected eight quarters, got {labels}"
    assert rows, "the sheet has no field_key rows"
    known = QUARTER_FIELDS + CONSENSUS_FIELDS
    assert all(k in known for k in rows), \
        f"unrecognised keys: {[k for k in rows if k not in known]}"
    # The street's numbers (item 3): the print-vs-consensus card reads them.
    for key in CONSENSUS_FIELDS:
        assert key in rows, f"the consensus row {key} is missing"
    for key in ("revenue", "net_income", "eps"):
        assert key in rows, f"an earnings video needs {key}"


# --------------------------------------------------------------------------
# O6.2 — both comparisons, labelled, never one.
# --------------------------------------------------------------------------


def test_qoq_and_yoy_are_both_derivable_and_disagree(workspace):
    """O6.2: the whole editorial point, on the fixture's own numbers.

    The fixture is seasonal on purpose: Q4 tops Q3 in both years by about
    the same margin. So the QoQ reads as a surge and the YoY reads as flat,
    and a script handed only the first number would call a seasonal December
    a turnaround.
    """
    data = load_company_data(workspace)
    moves = data.quarter_moves("revenue")

    assert moves["label"] == "Q4 FY-0"
    assert moves["qoq"]["pct"] == pytest.approx(15.6, abs=0.2)
    assert moves["yoy"]["pct"] == pytest.approx(0.7, abs=0.2)
    assert moves["qoq"]["from_label"] == "Q3 FY-0"
    assert moves["yoy"]["from_label"] == "Q4 FY-1"
    # The two must not be the same number, or the fixture is not seasonal
    # and this test proves nothing.
    assert abs(moves["qoq"]["pct"] - moves["yoy"]["pct"]) > 10


def test_the_prompt_block_labels_them_distinctly(workspace):
    """A single growth figure is the failure mode, not the output (O2)."""
    data = load_company_data(workspace)
    block = data.quarters_prompt_block()
    line = next(ln for ln in block.splitlines()
                if ln.strip().startswith("Q4 FY-0:") and "%" in ln)

    assert "QoQ" in line and "YoY same quarter" in line
    assert "+15.6%" in line and "+0.7%" in line
    assert line.index("QoQ") < line.index("YoY"), "QoQ first, then the honest one"
    # And the table itself is readable: a writer cannot say "1.41e+08".
    assert "141M" in block and "e+0" not in block


def test_a_rate_moves_in_points_not_percent(workspace):
    """A margin that went 58.0 → 57.6 did not fall 0.7%. It fell 0.4 points,
    and the percentage version is a figure nothing on the sheet contains."""
    data = load_company_data(workspace)
    moves = data.quarter_moves("gross_margin")
    assert moves["rate"] is True
    assert "pct" not in moves["qoq"] and "points" in moves["qoq"]
    assert moves["qoq"]["points"] == pytest.approx(-0.4, abs=0.05)
    assert "-0.4pts" in data.quarters_prompt_block()


def test_a_loss_is_reported_as_two_values_not_a_percentage(workspace):
    """CapEx going from -0.8M to -1.6M is spending that DOUBLED, and every
    percentage form of that reads as a cut: "-100%" against the negative
    base, "+100%" if you drop the sign. So neither is printed."""
    data = load_company_data(workspace)
    moves = data.quarter_moves("capex")
    assert "pct" not in moves["yoy"], "a percentage of a negative base is a trap"
    assert moves["yoy"]["change"] == pytest.approx(-800_000, abs=1)

    line = next(ln for ln in data.quarters_prompt_block().splitlines()
                if ln.strip().startswith("Q4 FY-0") and "800k" in ln)
    assert "-800k → -1.6M" in line, line
    assert "-100" not in line


def test_a_missing_yoy_says_so_rather_than_leaving_qoq_alone(settings):
    """Fewer than five quarters and there is no same-quarter comparison.
    Printing the QoQ by itself is exactly the misleading single figure."""
    from pipeline.models import CompanyData

    d = CompanyData(quarter_labels=["Q-2", "Q-1", "Q-0"],
                    quarters={"revenue": [100.0, 110.0, 160.0]})
    moves = d.quarter_moves("revenue")
    assert moves["qoq"]["pct"] == pytest.approx(45.45, abs=0.1)
    assert moves["yoy"] is None

    block = d.quarters_prompt_block()
    assert "YoY same quarter n/a (needs five quarters of history)" in block
    assert "QoQ +45.5%" in block


def test_the_writer_is_told_when_there_is_no_quarterly_data(settings):
    """A blank where a table should be is how the earnings format came to be
    written from training knowledge in the first place (O0)."""
    from bot.prompts import quarters_block
    from pipeline.models import CompanyData

    text = quarters_block(CompanyData())
    assert "no Quarters sheet" in text
    assert "Do not state a print" in text


def test_chart_metrics_names_the_quarterly_series_separately(workspace):
    """O5: a writer must not feature a quarterly row the sheet does not
    carry, and the annual and quarterly lists are genuinely different."""
    from bot.prompts import chart_metrics_line

    data = load_company_data(workspace)
    line = chart_metrics_line(data)
    assert "Quarterly series present" in line
    assert "eps" in line.split("Quarterly series present")[1]
    # A ticker with five years of revenue and no Quarters sheet says nothing.
    data.quarters = {}
    data.quarter_labels = []
    assert "Quarterly series present" not in chart_metrics_line(data)


def test_the_quarters_block_reaches_every_writing_prompt(workspace, settings,
                                                         tmp_path):
    """The payload table is checked against the templates both ways by
    `test_prompt_payload`; this is the other half — that the block arrives
    FILLED, with the fixture's own quarters in it."""
    from bot.prompts import PROMPT_FORMATS, fill_prompt

    data = load_company_data(workspace)
    for fmt in PROMPT_FORMATS:
        text = fill_prompt(fmt, "EXMPL", data, tmp_path, settings)
        assert "{{quarters}}" not in text, f"{fmt} left the token unfilled"
        assert "[quarters · 8 quarters" in text, f"{fmt} has no quarters"
        assert "YoY same quarter" in text, f"{fmt} shows one comparison only"


# --------------------------------------------------------------------------
# O6.3 — a wrong quarterly figure is caught.
# --------------------------------------------------------------------------


def test_a_fabricated_print_is_caught_against_the_quarterly_sheet(workspace):
    """O6.3. This is what makes the earnings format honest, and it only
    works after B4 removed the magnitude floor — quarterly figures are
    smaller than annual ones by construction."""
    from pipeline.gates import fact_check

    data = load_company_data(workspace)

    # The real print: 141M in Q4 FY-0.
    assert fact_check("Q4 revenue came in at a hundred and forty-one "
                      "million.", data) == []

    findings = fact_check("Q4 revenue came in at two hundred and forty "
                          "million.", data)
    assert findings, "an invented print reached the screen unchallenged"
    assert findings[0].severity == "block"
    assert "revenue" in findings[0].message
    assert "Q4" in findings[0].message, "the finding names the column it read"


def test_a_quarterly_figure_is_real_even_when_no_quarter_is_named(workspace):
    """The other half of O4, and the one the narrowing cannot cover.

    "Revenue came in at a hundred and forty-one million" names no period at
    all. 141M exists nowhere in the annual series — it is Q4's number — so
    unless the quarterly rows are in the bag `_series_for` builds, the
    fact-check calls a correct figure a fabrication and blocks the script.
    """
    from pipeline.gates import _series_for, fact_check

    data = load_company_data(workspace)
    assert 141_000_000 in _series_for(data, "revenue"), \
        "the quarterly rows are not in the bag the fact-check reads"
    assert fact_check("Revenue came in at a hundred and forty-one million.",
                      data) == []
    assert fact_check("Net income was minus twenty-four million.", data) == []
    # …and a number in neither sheet is still caught.
    assert fact_check("Revenue came in at a hundred and ninety million.",
                      data)


def test_the_check_narrows_to_the_quarter_the_sentence_names(workspace):
    """A figure from the wrong quarter is the failure B4 closed annually —
    Q3's 122M stated as Q1's is a fabrication about Q1."""
    from pipeline.gates import fact_check

    data = load_company_data(workspace)
    assert fact_check("Revenue in Q3 was a hundred and twenty-two million.",
                      data) == []
    findings = fact_check("Revenue in Q1 was a hundred and twenty-two "
                          "million.", data)
    assert findings, "122M is Q3's number, not Q1's"


def test_a_bare_quarter_number_does_not_block_a_correct_script(workspace):
    """An eight-quarter sheet has two Q4s. A gate that picks the newest and
    blocks a script meaning the other is worse than no gate: the one thing
    the fact-check must never do is refuse a correct script."""
    from pipeline.gates import fact_check

    data = load_company_data(workspace)
    # Q4 FY-1's revenue, stated with a bare "Q4".
    assert fact_check("Q4 revenue was a hundred and forty million.",
                      data) == []
    # …and Q4 FY-0's, the same way.
    assert fact_check("Q4 revenue was a hundred and forty-one million.",
                      data) == []


def test_naming_the_period_does_not_switch_the_gate_off(workspace):
    """`in Q4` and `in FY-0` were read as an attached SUBJECT — the rule that
    stops "two hundred million on sales and marketing" being a revenue claim
    — and since neither is a metric the export carries, the number was
    discarded. Naming the period is what a careful script does."""
    from pipeline.gates import fact_check

    data = load_company_data(workspace)
    for sentence in ("Net income was minus twelve million in FY-0.",
                     "Net income was minus forty million in Q4.",
                     "Revenue in the fourth quarter was three hundred million."):
        assert fact_check(sentence, data), f"unchecked: {sentence}"

    # The narrowing it must not break.
    assert fact_check("They spent two hundred and twelve million on sales "
                      "and marketing.", data) == []


def test_a_hyphenated_negative_is_read_with_its_sign(workspace):
    """"Minus twenty-four million" is how a writer spells it. The extractor
    rejoins a spoken run with single spaces, so recovering the position with
    `find` failed and both the minus sign and the metric-ownership scan were
    computed against character zero — reporting a correct figure as a
    fabrication, which for a blocking gate is the failure that matters."""
    from pipeline.gates import extract_numbers, fact_check

    data = load_company_data(workspace)
    nums = extract_numbers("net income was minus twenty-four million in q4.")
    spoken = next(n for n in nums if n.value == 24_000_000)
    assert spoken.start > 0 and spoken.end > spoken.start
    assert "minus" in "net income was minus twenty-four million in q4."[
        :spoken.start]

    assert fact_check("Net income was minus twenty-four million in Q4.",
                      data) == []
    assert fact_check("Net income was minus eighty-nine million in FY-0.",
                      data) == []


# --------------------------------------------------------------------------
# O6.4 / O3 — the filings: the 10-Qs, and the quarter the 10-K covers.
# --------------------------------------------------------------------------


def test_the_picker_returns_every_matching_filing_not_just_the_first(settings):
    """K2/O3: `_pick_filing` returned on the first match, with no parameter
    and no second entry point, so "the prior year's 10-K" was unreachable
    and so was the year-ago 10-Q."""
    from pipeline.filings import (
        ANNUAL_FORMS,
        QUARTERLY_FORMS,
        _load_submissions,
        pick_filings,
    )

    subs = _load_submissions("0001234567", settings)
    annual = pick_filings("0001234567", "EXMPL", subs, ANNUAL_FORMS)
    assert [r.period for r in annual] == ["2025-12-31", "2024-12-31",
                                          "2023-12-31"]
    quarterly = pick_filings("0001234567", "EXMPL", subs, QUARTERLY_FORMS)
    assert len(quarterly) == 6
    assert all(r.form == "10-Q" for r in quarterly)
    # Newest first, and every ref carries the period it REPORTS on rather
    # than the day it was filed — "the same quarter a year earlier" is a
    # statement about the period.
    assert quarterly[0].period == "2025-09-30"
    assert quarterly[0].filed == "2025-11-04"
    assert "000123456725000045" in quarterly[0].url   # EDGAR de-dashes it
    assert quarterly[0].accession == "0001234567-25-000045"


def test_the_reading_list_pairs_each_filing_with_its_year_earlier_twin(
        settings):
    """O3: the year-over-year quarterly comparison is the sharper diff — an
    annual report is up to twelve months stale."""
    from pipeline.filings import resolve_filings

    fs = resolve_filings("MEGA", settings)          # June fiscal year end
    assert fs.quarter_in_annual is False
    assert (fs.latest_annual.form, fs.latest_annual.period) == \
        ("10-K", "2025-06-30")
    assert (fs.prior_annual.form, fs.prior_annual.period) == \
        ("10-K", "2024-06-30")
    assert (fs.latest_quarter.form, fs.latest_quarter.period) == \
        ("10-Q", "2026-03-31")
    # THE SAME QUARTER, a year earlier — matched on the report date's
    # month and day, not on the filing date, which drifts by weeks.
    assert (fs.year_ago_quarter.form, fs.year_ago_quarter.period) == \
        ("10-Q", "2025-03-31")
    assert len(fs.refs()) == 4
    assert len({r.accession for r in fs.refs()}) == 4


def test_the_q4_case_still_produces_a_reading_list(settings):
    """O3's wrinkle: there is no fourth-quarter 10-Q — the 10-K covers it —
    so "last quarter" is sometimes inside the annual report. The picker has
    to handle that rather than returning nothing."""
    from pipeline.filings import resolve_filings

    fs = resolve_filings("EXMPL", settings)   # newest filing IS the 10-K
    assert fs.quarter_in_annual is True
    assert fs.latest_quarter is fs.latest_annual
    assert fs.year_ago_quarter is fs.prior_annual
    assert fs.refs(), "the Q4 case must not come back empty"
    assert [r.period for r in fs.refs()] == ["2025-12-31", "2024-12-31"]
    assert "no Q4 10-Q" in fs.describe()


def test_a_foreign_filer_degrades_to_an_empty_reading_list(settings):
    """A 20-F filer has no 10-K at all. An empty set, never an exception:
    the brief is an input to a writing prompt, and a thin brief beats a
    refused render."""
    from pipeline.filings import resolve_filings

    fs = resolve_filings("FRGN", settings)
    assert fs.refs() == []
    assert fs.latest_annual is None
    assert "no domestic filings" in fs.describe()
    assert resolve_filings("NOPE", settings).refs() == []


def test_two_filings_in_one_workspace_do_not_overwrite_each_other(
        settings, tmp_path):
    """K2: every filing was written to `filings/filing.html`, so the second
    download returned the first one's bytes — and a year-over-year brief
    would have read the same 10-K twice, silently."""
    from pipeline.filings import download_filing, filing_path, resolve_filings

    fs = resolve_filings("EXMPL", settings)
    a, b = fs.latest_annual, fs.prior_annual
    assert a.accession != b.accession

    pa = download_filing(a, tmp_path, settings)
    pb = download_filing(b, tmp_path, settings)
    assert pa is not None and pb is not None
    assert pa != pb, "two filings, one path"
    assert pa == filing_path(a, tmp_path) and pb == filing_path(b, tmp_path)
    assert a.accession in pa.name and b.accession in pb.name

    # And the path IS the cache: a second call re-reads rather than re-fetches.
    pa.write_text("marked", encoding="utf-8")
    assert download_filing(a, tmp_path, settings).read_text(
        encoding="utf-8") == "marked"


def test_a_workspace_written_before_the_rename_is_adopted(settings, tmp_path):
    """A live workspace has `filings/filing.html` in it already. Re-fetching
    from the SEC would be rude and slow; the file is the filing that was
    downloaded, so it is moved under the accession it belongs to."""
    from pipeline.filings import download_filing, filing_path, resolve_filings

    ref = resolve_filings("EXMPL", settings).latest_annual
    (tmp_path / "filings").mkdir(parents=True)
    (tmp_path / "filings" / "filing.html").write_text("old bytes",
                                                      encoding="utf-8")
    got = download_filing(ref, tmp_path, settings)
    assert got == filing_path(ref, tmp_path)
    assert got.read_text(encoding="utf-8") == "old bytes"
    assert not (tmp_path / "filings" / "filing.html").exists()


# --------------------------------------------------------------------------
# Naming the columns: "Boeing Q0 revenue" (30 Oct 2026).
# --------------------------------------------------------------------------
# His BA short printed `Q0` in a headline. The Quarters headers are relative
# (`Q-7` … `Q-0`) and are renamed only off the label rows; when those did not
# read as numbers, `Q-0` went to the writer as the quarter's name.

RELATIVE = [f"Q-{n}" for n in range(7, -1, -1)]


def _named(rows):
    from pipeline.company_data import _named_periods

    return _named_periods(list(RELATIVE), dict(rows), quarterly=True)[0]


def test_the_year_row_alone_names_every_quarter():
    """The quarter row did not resolve and the year row did: the column
    where the year ticks over is a Q1, and the rest follow."""
    years = [2024, 2025, 2025, 2025, 2025, 2026, 2026, 2026]
    names = _named({"fiscal_year": years, "fiscal_quarter": [None] * 8})
    assert names == ["Q4 FY24", "Q1 FY25", "Q2 FY25", "Q3 FY25", "Q4 FY25",
                     "Q1 FY26", "Q2 FY26", "Q3 FY26"]


@pytest.mark.parametrize("cell", [3, 3.0, "3", "Q3", "FQ3", "3Q", "Q3 2026"])
def test_a_quarter_cell_reads_however_the_add_in_writes_it(cell):
    names = _named({"fiscal_year": [None] * 7 + ["FY2026"],
                    "fiscal_quarter": [None] * 7 + [cell]})
    assert names[-1] == "Q3 FY26" and names[0] == "Q4 FY24"


def test_a_period_end_names_what_no_fiscal_row_does():
    import datetime as dt

    ends = [dt.date(2024, 12, 31), dt.date(2025, 3, 31), dt.date(2025, 6, 30),
            dt.date(2025, 9, 30), dt.date(2025, 12, 31), 46112.0,
            "06/30/2026", dt.datetime(2026, 9, 30)]
    names = _named({"period_end": ends})
    assert names[0] == "qtr to Dec '24"
    assert names[-1] == "qtr to Sep '26"
    assert names[-2] == "qtr to Jun '26"
    assert names[5] == "qtr to Mar '26"


def test_rows_that_contradict_each_other_name_nothing():
    """A year that skips (a moved year end) is a reason to keep the relative
    headers: a wrong quarter name is worse than an honest position."""
    years = [2024, 2025, 2025, 2025, 2025, 2025, 2026, 2026]
    assert _named({"fiscal_year": years}) == RELATIVE


def test_unresolved_label_cells_name_nothing():
    assert _named({"fiscal_year": ["#N/A"] * 8,
                   "fiscal_quarter": ["(Invalid Formula Name)"] * 8}) == RELATIVE


def test_the_loaded_workbook_names_the_print_quarter(workspace):
    """End to end, the shape of his workbook: relative headers, a year row
    that resolved, a quarter row that did not."""
    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    ws = wb["Quarters"]
    head = next(r for r in range(1, ws.max_row + 1)
                if ws.cell(r, 1).value == "field_key")
    for i in range(8):
        ws.cell(head, 3 + i, f"Q-{7 - i}")
    row = ws.max_row + 1
    ws.cell(row, 1, "fiscal_year")
    for i, y in enumerate([2024, 2025, 2025, 2025, 2025, 2026, 2026, 2026]):
        ws.cell(row, 3 + i, y)
    ws.cell(row + 1, 1, "fiscal_quarter")
    for i in range(8):
        ws.cell(row + 1, 3 + i, "(Invalid Formula Name)")
    wb.save(xlsx)
    wb.close()

    data = load_company_data(workspace)
    assert data.quarter_labels[-1] == "Q3 FY26"
    assert data.consensus()["label"] == "Q3 FY26"
    assert "fiscal_year" not in data.quarters
    assert "vs consensus, Q3 FY26" in data.quarters_prompt_block()


def test_an_unnamed_quarter_never_reaches_the_writer_as_q0(workspace):
    """When nothing names them, the columns are positions, and the prompt,
    the cards and the findings all say so in words."""
    from pipeline import short_data
    from pipeline.gates import _quarter_labels

    data = load_company_data(workspace)
    data.quarter_labels = list(RELATIVE)
    block = data.quarters_prompt_block()
    assert "Q-0" not in block and "Q-1 " not in block
    assert "vs consensus, latest quarter" in block
    assert "never a quarter number or Q0" in block
    assert data.consensus()["label"] == "latest quarter"

    card = short_data.print_vs_consensus(data)
    assert card and "Q-0" not in card["kicker"]
    assert card["kicker"].endswith("latest quarter")
    assert short_data.quarter_heads(data)[-1] == "LATEST"
    assert _quarter_labels(data)[-2:] == ["prior quarter", "latest quarter"]


def test_a_history_year_is_named_by_its_period_end_when_the_row_fails():
    import datetime as dt

    from pipeline.company_data import _named_periods

    periods = ["FY-4", "FY-3", "FY-2", "FY-1", "FY-0", "LTM"]
    ends = [dt.date(2021 + i, 12, 31) for i in range(5)] + [None]
    names, rows = _named_periods(periods, {"fiscal_year": ["#N/A"] * 6,
                                           "period_end": ends})
    assert names == ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"]
    assert rows == {}


def test_unnamed_years_come_with_a_warning_to_the_writer(workspace):
    data = load_company_data(workspace)
    assert data.history_years[-2] == "FY-0"
    assert "Never print FY-0" in data.as_prompt_block()
