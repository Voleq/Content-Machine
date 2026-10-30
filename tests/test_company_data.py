"""v3 company-data reader (§3): sheets read by NAME (Snapshot · History ·
Dashboard · Valuation · Peers), History period columns read dynamically
from the header row, CSV = snapshot-only, generic screenshot label."""

from pathlib import Path

import pytest
from PIL import Image

from pipeline.company_data import (
    CompanyDataError,
    FILING_SOURCE,
    find_export,
    list_screenshots,
    load_company_data,
    prepare_screenshot,
)
from pipeline.models import HISTORY_FIELDS


def test_load_snapshot_and_history(workspace):
    data = load_company_data(workspace)
    assert data.get("ticker") == "EXMPL"
    assert data.get("ps_ttm") == 62.0
    assert data.get("as_of_date") == "2026-07-01"
    assert data.blocking_missing == []

    assert data.has_history
    # periods are read dynamically from the header row (FY-4..FY-0, LTM)
    assert data.history_years == ["FY-4", "FY-3", "FY-2", "FY-1", "FY-0", "LTM"]
    assert data.history_row("revenue") == [400e6, 452e6, 471e6, 491e6, 496e6, 496e6]
    assert data.history_row("net_income")[-1] == -89e6
    assert set(data.history) <= set(HISTORY_FIELDS)


def test_dashboard_valuation_peers_surfaced(workspace):
    data = load_company_data(workspace)
    # the Dashboard summary — exactly what the numbers sheet reads
    assert data.dashboard_get("Net margin (LTM)") == -18.0
    assert data.dashboard_get("Profitable? (LTM NI>0)") == "no"
    assert data.dashboard_get("Diluting? (share CAGR>1%)") == "yes"
    # long-form context: bear/base/bull + peers
    assert data.has_valuation and len(data.valuation["scenarios"]) == 3
    assert data.valuation["current_price"] == 84.2
    assert data.has_peers and data.peers[0]["name"] == "Freightwave Systems Inc"


def test_news_parsing_skips_blanks_and_coerces_dates(workspace):
    data = load_company_data(workspace)
    # the blank spill row AND the NA-headline row are skipped
    assert len(data.news) == 5
    first = data.news[0]
    assert set(first) == {"date", "headline", "source", "url"}
    # real dates coerce to ISO day strings
    assert first["date"] == "2026-07-14"
    assert first["headline"].startswith("Example Corp posts record")
    assert first["url"] == "https://example.com/news/record-revenue"
    # every surviving row has a non-empty headline
    assert all(n["headline"] for n in data.news)
    # a news outlet as Source is fine; a data-terminal brand never reaches a field
    assert [n["source"] for n in data.news] == [
        "Reuters", "Bloomberg", "Associated Press", "CNBC", "Business Wire",
    ]
    blob = " ".join(str(v) for n in data.news for v in n.values()).lower()
    for brand in ("refinitiv", "lseg", "capital iq"):
        assert brand not in blob


def test_peer_percentiles_parsing_and_block_separation(workspace):
    data = load_company_data(workspace)
    pcts = data.peer_percentiles
    assert len(pcts) == 10
    by_metric = {p["metric"]: p for p in pcts}
    # values + a 0-1 percentile fraction + direction + read
    pe = by_metric["P/E (TTM)"]
    assert pe["subject"] == 34.0 and pe["median"] == 37.5
    assert pe["percentile"] == 0.42 and pe["direction"] == "worse"
    assert pe["read"] == "mid-pack"
    rg = by_metric["Rev growth % (3Y CAGR)"]
    assert rg["direction"] == "better" and rg["read"] == "strong vs peers"
    assert rg["percentile"] == 0.80
    assert by_metric["P/S (TTM)"]["read"] == "expensive vs peers"
    assert all(0.0 <= p["percentile"] <= 1.0 for p in pcts)
    assert {p["direction"] for p in pcts} == {"better", "worse"}
    # the two blocks are DISTINCT: the auto peer table did not consume the
    # percentile rows, and the percentile reader did not grab peer names
    assert [p["name"] for p in data.peers] == [
        "Freightwave Systems Inc", "DepotOps Corp",
        "RouteLogic Holdings", "CargoCloud Inc",
    ]
    assert {p["name"] for p in data.peers}.isdisjoint(by_metric)


def test_peer_columns_are_mapped_by_header_not_position(workspace):
    """Pin the peer mapping to the sheet the template actually ships:

        B Price · C Market Cap · D P/E · E EV/EBITDA · F P/S · G Gross Mgn % ·
        H Net Mgn % · I FCF Yield % · J NetDebt/EBITDA · K Rev LTM (now) ·
        L Rev LTM (-3Y) · M Rev Growth % (3Y CAGR)

    The table grew the two revenue feeds and the computed CAGR, pushing
    everything from the margins one column right. Reading fixed offsets B–K
    mislabelled five fields at once — gross margin arriving as `rev_growth`,
    net margin as `gross_margin`, FCF yield as `net_margin`, net debt/EBITDA
    as `fcf_yield`, and a raw revenue figure as `net_debt_ebitda` — each one
    plausible enough on its own to reach a script.
    """
    data = load_company_data(workspace)
    top = data.peers[0]
    assert set(top) == {
        "name", "price", "market_cap", "pe", "ev_ebitda", "ps", "gross_margin",
        "net_margin", "fcf_yield", "net_debt_ebitda", "rev_growth",
    }
    assert top["name"] == "Freightwave Systems Inc"
    assert top["price"] == 142.0
    assert top["market_cap"] == 12_400_000_000
    assert top["pe"] == 34.0
    assert top["ev_ebitda"] == 22.0
    assert top["ps"] == 9.1
    assert top["gross_margin"] == 71.0
    assert top["net_margin"] == 6.0
    assert top["fcf_yield"] == 2.1
    assert top["net_debt_ebitda"] == 0.4
    # rev_growth is the COMPUTED 3Y CAGR (col M) — ((K/L)^(1/3)-1)*100
    assert top["rev_growth"] == pytest.approx(18.0, abs=1e-3)

    # the exact off-by-one the fixed offsets produced, field by field
    assert top["rev_growth"] != 71.0, "gross margin read as revenue growth"
    assert top["gross_margin"] != 6.0, "net margin read as gross margin"
    assert top["net_margin"] != 2.1, "FCF yield read as net margin"
    assert top["fcf_yield"] != 0.4, "net debt/EBITDA read as FCF yield"
    # …and the raw revenue feeds (cols K/L) reach no field at all
    feeds = {2037.36, 1240.0, 1269.13, 980.0, 3813.28, 2100.0, 726.52, 610.0}
    read = {v for p in data.peers for k, v in p.items() if k != "name"}
    assert not (feeds & read), "a raw `Rev LTM` figure landed in a metric field"

    # NA cells still coerce to None, and negative margins survive
    depot = data.peers[1]
    assert depot["name"] == "DepotOps Corp"
    assert depot["pe"] is None                # '#N/A' in the fixture
    assert depot["ev_ebitda"] == 41.0
    assert depot["gross_margin"] == 62.0 and depot["net_margin"] == -4.0
    assert depot["net_debt_ebitda"] == 1.8
    assert depot["rev_growth"] == pytest.approx(9.0, abs=1e-3)
    assert data.peers[3]["fcf_yield"] is None  # '#N/A' — not the neighbour's


def test_peer_columns_are_found_however_the_template_orders_them():
    """Column ORDER is not the contract, the header text is.

    The pre-CAGR revision carried a raw `Rev Growth %` sixth, straight after
    `P/S`; the current one computes a 3Y CAGR at the far right, past two
    revenue feeds. Both must read to the same fields — as must a sheet whose
    columns simply sit in another order, or whose margins are spelled out.
    """
    from openpyxl import Workbook

    from pipeline.company_data import _read_peers

    expected = {
        "name": "Freightwave Systems Inc", "price": 142.0,
        "market_cap": 12_400_000_000, "pe": 34.0, "ev_ebitda": 22.0, "ps": 9.1,
        "gross_margin": 71.0, "net_margin": 6.0, "fcf_yield": 2.1,
        "net_debt_ebitda": 0.4, "rev_growth": 18.0,
    }
    # whatever a revision titles a column, this is what belongs under it
    by_header = {
        "Peer (auto)": expected["name"], "Price": 142.0,
        "Market Cap": 12_400_000_000, "P/E": 34.0, "EV/EBITDA": 22.0,
        "P/S": 9.1, "Gross Mgn %": 71.0, "Gross margin %": 71.0,
        "Net Mgn %": 6.0, "Net margin %": 6.0, "FCF Yield %": 2.1,
        "NetDebt/EBITDA": 0.4, "Net debt / EBITDA": 0.4,
        "Rev Growth %": 18.0, "Rev Growth % (3Y CAGR)": 18.0,
        # the feeds behind the CAGR — read by nothing
        "Rev LTM (now)": 2037.36, "Rev LTM (-3Y)": 1240.0,
    }
    layouts = [
        # the pre-CAGR revision — raw growth sixth
        ["Peer (auto)", "Price", "Market Cap", "P/E", "EV/EBITDA", "P/S",
         "Rev Growth %", "Gross Mgn %", "Net Mgn %", "FCF Yield %",
         "NetDebt/EBITDA"],
        # what ships today — feeds, then the computed CAGR, at the far right
        ["Peer (auto)", "Price", "Market Cap", "P/E", "EV/EBITDA", "P/S",
         "Gross Mgn %", "Net Mgn %", "FCF Yield %", "NetDebt/EBITDA",
         "Rev LTM (now)", "Rev LTM (-3Y)", "Rev Growth % (3Y CAGR)"],
        # reordered, margins spelled out, the name column no longer first
        ["Rev Growth % (3Y CAGR)", "Net debt / EBITDA", "Peer (auto)",
         "Net margin %", "Gross margin %", "FCF Yield %", "P/S", "EV/EBITDA",
         "P/E", "Market Cap", "Price"],
    ]
    for layout in layouts:
        wb = Workbook()
        ws = wb.active
        ws.title = "Peers"
        for j, title in enumerate(layout, 1):
            ws.cell(row=4, column=j, value=title)
            ws.cell(row=5, column=j, value=by_header[title])
        assert _read_peers(ws) == [expected], layout


def test_valuation_wacc_and_reverse_dcf_keys(workspace):
    data = load_company_data(workspace)
    val = data.valuation
    # the bare 'WACC' row — NOT the 'WACC (auto — CAPM)' band title nor the
    # 'WACC −1%' / 'WACC +1%' sensitivity rows (Unicode-minus labels)
    assert val["wacc"] == 0.092
    # the reverse-DCF row, not the later 'Implied growth sensitivity …' title
    assert val["implied_growth"] == 0.061
    assert val["hist_fcf_cagr"] == 0.045
    assert val["rev_cagr"] == 0.12
    assert val["priced_vs_delivered"] == 0.016
    # a free-text verdict, kept verbatim as a string
    assert val["reverse_dcf_read"] == "market prices in MORE growth than history delivered"
    # the existing bear/base/bull scenario reader is untouched
    assert len(val["scenarios"]) == 3


def test_a_scenario_names_its_metric_not_its_figure(workspace):
    """The real template's scenario rows carry the per-share figure in B
    (`=B6`, the LTM EPS) and its name in C. Read as text first, B gave the
    writer "metric=4.25"."""
    from openpyxl import load_workbook

    xlsx = workspace / "dennis_data.xlsx"
    assert [s["metric"] for s in load_company_data(workspace).valuation["scenarios"]] \
        == ["P/S"] * 3                          # the fixture's older layout
    wb = load_workbook(xlsx)
    ws = wb["Valuation"]
    for row in ws.iter_rows():
        if str(row[0].value or "").strip() in ("Bear", "Base", "Bull"):
            row[1].value, row[2].value = 4.25, "EPS"
    wb.save(xlsx)
    got = load_company_data(workspace).valuation["scenarios"]
    assert [(s["metric"], s["per_share"]) for s in got] == [("EPS", 4.25)] * 3


def test_missing_news_sheet_degrades(workspace):
    # dropping the OPTIONAL News sheet must degrade (news == []), never raise
    from openpyxl import load_workbook

    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    wb.remove(wb["News"])
    wb.save(xlsx)
    data = load_company_data(workspace)
    assert data.news == []
    # the other optional blocks are unaffected
    assert data.has_peers and len(data.peer_percentiles) == 10


def test_prompt_block_carries_history_and_dashboard(workspace):
    data = load_company_data(workspace)
    block = data.as_prompt_block()
    assert "[history" in block
    assert "revenue:" in block and "FY-0" in block
    assert "[dashboard" in block and "Net margin (LTM):" in block
    # the vendor is never named (only the RIC ticker itself may carry a dot)
    assert "refinitiv" not in block.lower() and "lseg" not in block.lower()


def test_csv_is_snapshot_only(workspace, fixtures_dir):
    (workspace / "dennis_data.xlsx").unlink()
    csv_src = fixtures_dir / "company_data" / "dennis_data.csv"
    (workspace / "dennis_data.csv").write_bytes(csv_src.read_bytes())
    data = load_company_data(workspace)
    assert data.get("ticker") == "EXMPL"
    assert not data.has_history, "CSV carries no history sheet"
    assert data.news == [] and data.peer_percentiles == []


def test_missing_export_raises(settings):
    empty = settings.workspace_dir / "NONE" / "2026-07-01"
    empty.mkdir(parents=True)
    assert find_export(empty) is None
    with pytest.raises(CompanyDataError, match="dennis_data"):
        load_company_data(empty)


def test_na_values_and_unknown_fields(workspace):
    data = load_company_data(workspace)
    assert data.get("pe_ttm") is None       # '#N/A' in the fixture
    assert "pe_ttm" in data.warning_missing


def test_the_value_column_is_found_however_the_template_titles_it(tmp_path):
    """The v3.1 template renamed `Value (auto)` to `Value (Capital IQ) MM`.

    An exact-match column lookup read ZERO snapshot fields off it — a workbook
    that was present, opened cleanly, and parsed to nothing, which then looks
    identical to "the operator never refreshed it". Match on the prefix.
    """
    from openpyxl import Workbook

    for title in ("Value (auto)", "Value", "Value (Capital IQ) MM",
                  "Value (Refinitiv)"):
        wb = Workbook()
        ws = wb.active
        ws.title = "Snapshot"
        ws.cell(row=6, column=2, value="field_key")
        ws.cell(row=6, column=3, value="Label")
        ws.cell(row=6, column=4, value=title)
        for i, (k, v) in enumerate([("company_name", "Example Inc"),
                                    ("ticker", "EXMPL"),
                                    ("as_of_date", "2026-07-01"),
                                    ("price", 12.5),
                                    ("market_cap", 1.0e9),
                                    ("shares_out", 8.0e7)]):
            ws.cell(row=7 + i, column=2, value=k)
            ws.cell(row=7 + i, column=4, value=v)
        d = tmp_path / title.replace(" ", "_").replace("(", "").replace(")", "")
        d.mkdir(parents=True)
        wb.save(d / "dennis_data.xlsx")

        data = load_company_data(d)
        assert data.get("company_name") == "Example Inc", f"{title!r} read nothing"
        assert data.blocking_missing == [], title


def test_the_shipped_template_parses_structurally(tmp_path):
    """Guard the whole contract: whatever revision of the template ships, its
    Snapshot sheet must still be readable by field_key."""
    import shutil
    from pathlib import Path

    template = Path(__file__).resolve().parents[1] / "templates" / "dennis_data_template.xlsx"
    d = tmp_path / "ws"
    d.mkdir(parents=True)
    shutil.copy(template, d / "dennis_data.xlsx")

    # The shipped template holds formulas with no cached values, so every value
    # reads None — but the KEYS must all be found, which is what broke.
    from pipeline.company_data import _read_snapshot
    from openpyxl import load_workbook
    from pipeline.models import ALL_DATA_FIELDS

    wb = load_workbook(d / "dennis_data.xlsx", data_only=True)
    pairs = _read_snapshot(wb["Snapshot"])
    wb.close()
    assert len(pairs) >= 40, f"only {len(pairs)} field_keys found in the template"
    unknown = [k for k in pairs if k not in ALL_DATA_FIELDS]
    assert not unknown, f"template has field_keys the model doesn't know: {unknown}"

    # THE HISTORY CONTRACT IS ITS SHAPE, NOT ITS CONTENT. A blank template
    # holds formulas and no cached values — which is what the docstring above
    # says and what a template SHOULD be. This used to assert `has_history`,
    # and it passed only because the committed workbook still carried one
    # ticker's cached refresh; the delta-09b template ships without it, so the
    # assertion was reading somebody's leftover Alphabet numbers as proof that
    # the parser worked. The periods are the part that must survive a revision.
    data = load_company_data(d)
    assert data.history_years == ["FY-4", "FY-3", "FY-2", "FY-1", "FY-0", "LTM"]
    assert set(data.history), "the History sheet lost its field_key rows"


def test_the_shipped_template_peer_table_maps_every_field():
    """The peer half of the same contract, against the REAL workbook: whatever
    revision ships, every field must find its OWN column, `rev_growth` must be
    the computed 3Y CAGR, and no raw `Rev LTM` figure may reach a metric."""
    from pathlib import Path

    from openpyxl import load_workbook

    from pipeline.company_data import (
        _PEER_COLS,
        _cell_text,
        _col_of,
        _header_row,
        _num,
        _read_peers,
        _rows,
    )

    template = Path(__file__).resolve().parents[1] / "templates" / "dennis_data_template.xlsx"
    wb = load_workbook(template, data_only=True)
    ws = wb["Peers"]
    rows = _rows(ws)
    hr = _header_row(rows, "peer (auto)")
    assert hr is not None, "the auto peer table lost its `Peer (auto)` header"
    header = rows[hr]

    cols = {f: _col_of(header, *names) for f, names in _PEER_COLS.items()}
    assert all(c is not None for c in cols.values()), \
        f"no column found for {[f for f, c in cols.items() if c is None]}"
    # one column each: never two fields on one, never a `cln …` scoring twin
    assert len(set(cols.values())) == len(cols)
    titles = {f: _cell_text(header[c]).lower() for f, c in cols.items()}
    assert not any(t.startswith("cln") for t in titles.values()), titles
    assert "cagr" in titles["rev_growth"] and "ltm" not in titles["rev_growth"]

    # Same reasoning as the History assertion above: a blank template's auto
    # table is a PEERS() spill with nothing cached in it, so the number of rows
    # it happens to carry is whichever refresh was last saved into the file —
    # not the contract. What must hold is that every row it DOES carry reads a
    # name and keeps the revenue feeds out of the metrics.
    peers = _read_peers(ws)
    assert all(p["name"] for p in peers)
    # per row, the two revenue feeds must not appear in any metric — that is
    # exactly what the fixed-offset read did (`Rev LTM (now)` ≈ 1e5 arriving
    # as a net-debt/EBITDA ratio).
    feed_cols = [c for c in (_col_of(header, "rev ltm (now)"),
                             _col_of(header, "rev ltm (-3y)")) if c is not None]
    assert feed_cols, "the template dropped the revenue feeds"
    for row, peer in zip(rows[hr + 1:], peers):
        fed = {_num(row[c]) for c in feed_cols if c < len(row)} - {None}
        metrics = {v for k, v in peer.items() if k != "name" and v is not None}
        assert not (fed & metrics), peer["name"]
    wb.close()


def test_screenshot_gets_design_s_source_tag(workspace, settings, tmp_path):
    """The filing, never the vendor, on design's own tag where the kit rests it.

    It was a bot-drawn chip in terminal green and Space Mono, the look from
    before the kit. The tag's spot is `moves.tag_rect` with no plate under it.
    """
    from pipeline.moves import tag_rect
    from pipeline.plates import load_plates

    src = tmp_path / "raw.png"
    Image.new("RGB", (1400, 800), (30, 34, 40)).save(src)
    out = prepare_screenshot(src, tmp_path / "norm.png", settings)
    img = Image.open(out).convert("RGB")
    assert img.size == settings.long_resolution
    assert FILING_SOURCE == "10-K"

    reg = load_plates(settings.assets_dir)
    tag = reg.get(reg.aspect_key("overlays/source-tag", "16x9"))
    x, y, w, h = tag_rect(tag, None, img.size, reg)
    # The flat screenshot is one colour; the tag's ground and type are others.
    colors = img.crop((x, y, x + w, y + h)).getcolors(maxcolors=65536)
    assert colors and len(colors) > 2, "the source tag must be on the card"
    # And nothing is drawn in the corner the old chip sat in.
    corner = img.crop((0, 0, 200, 60)).getcolors(maxcolors=65536)
    assert corner and len(corner) <= 2


def test_list_screenshots_excludes_exports(workspace):
    (workspace / "income_statement.png").write_bytes(b"png")
    (workspace / "_hidden.png").write_bytes(b"png")
    shots = list_screenshots(workspace)
    assert shots == ["income_statement.png"]


def test_the_uploads_age_reads_a_date_as_the_freshness_gate_does():
    """09/03/2026 on a US sheet is 9 March. The upload read it day-first as
    3 September while the gate read 9 March: one said fresh, one stale."""
    import datetime as dt

    from pipeline.company_data import _as_of_age_days
    from pipeline.gates import _parse_as_of

    today = dt.date(2026, 9, 10)
    assert _parse_as_of("09/03/2026") == dt.date(2026, 9, 3)
    assert _as_of_age_days("09/03/2026", today) == 7
    assert _as_of_age_days("2026-09-03", today) == 7
    assert _as_of_age_days("Sep 3, 2026", today) == 7
    assert _as_of_age_days("not a date", today) is None


def _in_millions(path):
    """The fixture rewritten the way a Capital IQ pull fills the template:
    the value column titled `Value (Capital IQ) MM`, every amount of money
    and every share count in millions."""
    from openpyxl import load_workbook

    from pipeline.models import MILLIONS_DASHBOARD, MILLIONS_FIELDS

    wb = load_workbook(path)
    for name in ("Snapshot", "History", "Quarters", "Dashboard"):
        for row in wb[name].iter_rows():
            key = next((c.value for c in row[:2] if c.value in MILLIONS_FIELDS
                        or (name == "Dashboard" and c.value in MILLIONS_DASHBOARD)),
                       None)
            for c in row:
                if c.value == "Value (auto)":
                    c.value = "Value (Capital IQ) MM"
                elif key and isinstance(c.value, (int, float)):
                    c.value = c.value / 1e6
    wb.save(path)


def test_a_workbook_in_millions_reads_in_whole_units(workspace):
    """The real template pulls Capital IQ in millions (its value column says
    MM). A quarter's revenue of 150.0 printed "$150" on the cards and in the
    prompts; it is read as 150 million, like the fixture."""
    from pipeline.short_data import fmt

    whole = load_company_data(workspace)
    _in_millions(workspace / "dennis_data.xlsx")
    data = load_company_data(workspace)

    assert data.history_row("revenue") == pytest.approx(whole.history_row("revenue"))
    assert data.get("market_cap") == pytest.approx(whole.get("market_cap"))
    assert data.get("shares_out") == pytest.approx(whole.get("shares_out"))
    assert data.get("price") == whole.get("price")
    assert data.history_row("eps") == whole.history_row("eps")
    assert data.history_row("gross_margin") == whole.history_row("gross_margin")
    assert data.quarters["revenue"] == pytest.approx(whole.quarters["revenue"])
    assert data.dashboard_get("Market cap") == pytest.approx(
        whole.dashboard_get("Market cap"))
    card = fmt("revenue", data.quarters["revenue"][-1])
    assert card == fmt("revenue", whole.quarters["revenue"][-1])
    assert card.startswith("$") and card.endswith("M")


# --------------------------------------------------------------------------
# The workbook audit (30 Oct 2026): what an older template computed wrongly.
# --------------------------------------------------------------------------

def _edit(workspace, sheet, edits, value_offset=2):
    """Overwrite cells on one sheet of the workspace's workbook: by
    coordinate, by `(field_key, period index)`, or by `(label, None)` for the
    value `value_offset` columns right of the label."""
    from openpyxl import load_workbook

    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    ws = wb[sheet]
    for where, value in edits.items():
        if isinstance(where, str):
            ws[where] = value
            continue
        key, idx = where
        row = next(r for r in range(1, ws.max_row + 1)
                   if str(ws.cell(r, 1).value or "").strip() == key
                   or str(ws.cell(r, 2).value or "").strip() == key)
        if idx is None:
            col = next(c for c in range(1, ws.max_column + 1)
                       if str(ws.cell(row, c).value or "").strip() == key) + value_offset
        else:
            col = 3 + idx
        ws.cell(row, col).value = value
    wb.save(xlsx)
    wb.close()


def test_growth_between_two_losses_is_not_a_growth_rate(workspace):
    """BA's free cash flow went from -4.4B to -1.9B, and the sheet's CAGR
    said it "delivered -19.2%" a year. That and the reverse DCF on negative
    cash ("9.4% perpetual growth") are blanked, with the verdict built on
    them; the WACC beside them stands."""
    _edit(workspace, "History", {("fcf", 0): -4396e6, ("fcf", 4): -1877e6,
                                 ("fcf", 5): -357e6})
    from openpyxl import load_workbook

    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    ws = wb["Valuation"]
    r = ws.max_row + 2
    ws.cell(r, 1, "FCF base (LTM)")
    ws.cell(r, 2, -357)
    wb.save(xlsx)
    wb.close()

    val = load_company_data(workspace).valuation
    assert val["hist_fcf_cagr"] is None
    assert val["implied_growth"] is None
    assert val["priced_vs_delivered"] is None and val["reverse_dcf_read"] is None
    assert val["wacc"] == 0.092 and "fcf_base" not in val

    from pipeline import short_data
    from bot.prompts import valuation_data_block

    data = load_company_data(workspace)
    assert short_data.implied(data) is None
    assert "verdict" not in valuation_data_block(data)


def _repaired(history=None, values=None, valuation=None, dashboard=None,
              years=("FY21", "FY22", "FY23", "FY24", "FY25", "LTM")):
    from pipeline.company_data import _repair

    values = dict(values or {})
    history = {k: list(v) for k, v in (history or {}).items()}
    valuation = dict(valuation or {})
    dashboard = dict(dashboard or {})
    _repair(values, list(years), history, {}, dashboard, valuation, [])
    return values, history, valuation, dashboard


def test_a_loss_per_share_gets_no_scenario_price():
    sc = [{"scenario": "Base", "per_share": -1.5, "exit_multiple": 20,
           "implied_price": -30.0, "upside_pct": -118.0},
          {"scenario": "Bull", "per_share": 2.0, "exit_multiple": 20,
           "implied_price": 40.0, "upside_pct": 5.0}]
    _, _, val, _ = _repaired(valuation={"scenarios": sc})
    assert val["scenarios"][0]["implied_price"] is None
    assert val["scenarios"][0]["upside_pct"] is None
    assert val["scenarios"][1]["implied_price"] == 40.0


def test_ratios_over_a_negative_base_are_blank():
    """BA's equity is negative: a loss over it is a positive "ROE"."""
    M = 1e6
    values, hist, _, dash = _repaired(
        history={"total_equity": [5e9, 4e9, 1e9, -3.9e9, -3.3e9, -3.9e9],
                 "roe": [10.0, 5.0, 2.0, 302.0, 250.0, 302.0],
                 "ebitda": [2400 * M, 1668 * M, 3792 * M, -11748 * M, -4652 * M, -50 * M],
                 "net_debt_ebitda": [10.0, 12.0, 5.0, -2.0, -4.0, -20.0]},
        values={"net_debt_ebitda_now": -20.0, "net_debt_now": 30e9},
        dashboard={"Over-levered? (ND/EBITDA>3x)": "no"})
    assert hist["roe"] == [10.0, 5.0, 2.0, None, None, None]
    assert hist["net_debt_ebitda"][-3:] == [None, None, None]
    assert values["net_debt_ebitda_now"] is None
    assert dash["Over-levered? (ND/EBITDA>3x)"] == "yes"


def test_the_fcf_yield_that_never_resolved_is_rebuilt(workspace):
    """`fcf_yield did not resolve (#NAME?)` in his BA log: the template's
    LSEG call. The same figure off the sheet's own cash flow and size."""
    _edit(workspace, "Snapshot", {("fcf_yield", None): "#NAME?"})
    data = load_company_data(workspace)
    fcf = data.history["fcf"][-1]
    assert data.get("fcf_yield") == pytest.approx(fcf / data.get("market_cap"))


def test_a_flag_on_an_empty_cell_is_no_answer(workspace):
    """In Excel `"" > 0` is TRUE, so a blank figure flagged the company
    profitable, diluting and over-levered at once."""
    _edit(workspace, "Dashboard", {("Profitable? (LTM NI>0)", None): "yes",
                                   ("Share count 4y CAGR", None): None,
                                   ("Diluting? (share CAGR>1%)", None): "yes"},
          value_offset=1)
    data = load_company_data(workspace)
    assert data.dashboard_get("Profitable? (LTM NI>0)") == "no"   # NI is a loss
    assert data.dashboard_get("Diluting? (share CAGR>1%)") is None


def test_country_is_a_country_and_diluted_shares_are_diluted(workspace):
    _edit(workspace, "Snapshot", {
        ("country", None): "100 N Riverside, Chicago, Illinois, 60606, United States"})
    data = load_company_data(workspace)
    assert data.get("country") == "United States"
    assert data.get("shares_dill_out") == data.quarters["diluted_shares"][-1]


def test_a_news_column_repeating_the_headline_is_dropped(workspace):
    head = "Example Corp posts record quarterly revenue, tops estimates"
    _edit(workspace, "News", {"A5": head, "C5": head, "D5": head})
    data = load_company_data(workspace)
    first = next(n for n in data.news if n["headline"] == head)
    assert first["date"] is None and first["source"] is None and first["url"] is None


def test_news_that_never_names_the_company_is_listed_apart(workspace):
    """The terminal's news for META came back as market round-ups ("Apple
    pays $17B in Irish taxes"). The writer sees them marked, after the
    company's own."""
    data = load_company_data(workspace)
    data.news = [{"headline": "Apple pays $17B in Irish taxes"},
                 {"headline": "Example Corp posts record quarterly revenue"},
                 {"headline": "EXMPL slides after guidance cut"}]
    block = data.as_prompt_block()
    news = block[block.index("[news"):]
    assert news.index("Example Corp posts") < news.index("not naming the company")
    assert news.index("EXMPL slides") < news.index("not naming the company")
    assert news.index("not naming the company") < news.index("Apple pays")
    assert data.names_company("Boeing misses") is False


# --------------------------------------------------------------------------
# The template itself.
# --------------------------------------------------------------------------

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "dennis_data_template.xlsx"


def _template(**kw):
    from openpyxl import load_workbook

    return load_workbook(TEMPLATE, **kw)


def test_the_template_carries_no_other_company_s_rows():
    """GameStop's peers and its top headline were saved into the template as
    plain values. A ticker with fewer peers kept GameStop's tail under its
    own, and every News sheet opened on a GameStop headline."""
    wb = _template()
    peers = wb["Peers"]
    for r in range(5, 55):
        for c in "ABCDEFGHIJKLWXY":
            v = peers[f"{c}{r}"].value
            assert v is None or (isinstance(v, str) and v.startswith("=")), \
                f"Peers!{c}{r} holds a saved value: {v!r}"
    news = wb["News"]
    for c in "ABCD":
        assert news[f"{c}7"].value is None
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert not (isinstance(cell.value, str) and '"GME"' in cell.value), \
                    f"{ws.title}!{cell.coordinate} is pinned to GME"


def test_the_template_calls_no_function_his_excel_lacks():
    """`_xll.RDP.Data` showed `#NAME?` on his terminal (BA proof log)."""
    wb = _template()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert not (isinstance(cell.value, str) and cell.value.startswith("=")
                            and "RDP.Data" in cell.value), f"{ws.title}!{cell.coordinate}"


def test_the_template_names_its_quarters_and_guards_its_math():
    from pipeline.company_data import _read_quarters

    wb = _template()
    labels, rows = _read_quarters(wb["Quarters"])
    assert len(labels) == 8 and "period_end" not in rows
    q = wb["Quarters"]
    row = next(r for r in range(1, q.max_row + 1) if q.cell(r, 1).value == "period_end")
    assert "IQ_PERIODDATE" in q.cell(row, 10).value
    h = wb["History"]
    assert "N(C15)>0" in h["I15"].value and "N(G15)>0" in h["I15"].value
    assert "N(C24)>0" in h["C32"].value          # ROE over positive equity only
    v = wb["Valuation"]
    assert "N(B32)>0" in v["B34"].value           # no implied growth on no cash
    assert "ISNUMBER(B35)" in v["B38"].value      # no verdict on a blank
    d = wb["Dashboard"]
    for r in range(23, 28):
        assert "ISNUMBER" in d[f"B{r}"].value, f"Dashboard!B{r}"
    s = wb["Snapshot"]
    assert "IQ_CQ" in s["D44"].value and "IQ_CQ" in s["D45"].value
    assert s["D19"].value == "=Quarters!J22"


def test_the_template_keeps_no_stale_range_names():
    """The plug-in tracks each CIQRANGE output with a hidden `IQR…` name.
    One pointing at cells that hold other formulas is a range a refresh may
    clear as its own."""
    wb = _template()
    for name, dn in wb.defined_names.items():
        if not name.startswith("IQR"):
            continue
        for sheet, ref in dn.destinations:
            ws = wb[sheet]
            for row in ws[ref.replace("$", "")] if ":" in ref else [[ws[ref.replace("$", "")]]]:
                for cell in row:
                    assert not (isinstance(cell.value, str) and cell.value.startswith("=")
                                and "CIQ" not in cell.value), f"{name} -> {sheet}!{cell.coordinate}"
