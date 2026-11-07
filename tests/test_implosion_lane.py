"""The implosion long: one famous blow-up, told from its documents.

No workbook and no ticker. The bot reads the story's documents (a regulator's
order, a prosecutor's release, a court's judgment), numbers every sentence so
a figure in the video can point at one, and writes the two prompts from them.
Every ticker-shaped step (prices, the filing pull, the freshness gate) stands
aside for a story code.

Fixtures only: the order and the release under `fixtures/implosions/docs/`
are made up and say so in their first sentence. Nothing here touches the
network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bot.handlers import BotCore
from pipeline import implosions as im
from pipeline import story_docs as sd
from pipeline.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gen_fixtures import IMPLOSION_ORDER_PAGES, tiny_pdf  # noqa: E402

CHAT = 4401
DOCS = ROOT / "fixtures" / "implosions" / "docs"
ALL_LISTS = ("List of trading losses|List of corporate collapses and scandals|"
             "List of stock market crashes and bear markets|List of example blow-ups")


@pytest.fixture()
def every_list(settings):
    return settings.model_copy(update={"implosion_lists": ALL_LISTS,
                                       "operator_chat_ids": [CHAT]})


@pytest.fixture()
def core(every_list):
    im.refresh(every_list)
    return BotCore(every_list)


def _knight(core) -> Workspace:
    reply = core.start_implosion(CHAT, ["Knight"])
    assert "IMPLOSION" in reply.text, reply.text
    return core.context.get(CHAT)


# ------------------------------------------------------- reading documents


def test_the_committed_fixtures_are_what_the_generator_writes():
    """The PDF is built by `scripts/gen_fixtures.py`, which the install
    runs: a hand edit to the committed file would be undone on his box."""
    got = tiny_pdf(IMPLOSION_ORDER_PAGES,
                   "FIXTURE: In the Matter of Knight Capital Americas LLC")
    assert got == (DOCS / "knight-order.pdf").read_bytes()


def test_a_pdf_is_read_sentence_by_sentence_with_its_page():
    info = sd.read_bytes((DOCS / "knight-order.pdf").read_bytes(), name="order.pdf")
    assert info["type"] == "pdf" and info["pages"] == 2 and not info["why"]
    assert info["title"].startswith("FIXTURE")
    by_n = {s["n"]: s for s in info["sentences"]}
    # A sentence wrapped over two lines is one sentence.
    assert by_n[3]["text"] == ("On August 1, 2012, the Respondent sent more than 4 "
                               "million orders into the market in 45 minutes while "
                               "trying to fill 212 customer orders.")
    assert by_n[3]["page"] == 1
    assert by_n[5]["page"] == 2 and "$460 million" in by_n[5]["text"]
    assert "without admitting or denying" in by_n[7]["text"]


def test_a_page_keeps_its_prose_and_its_dateline_and_drops_the_chrome():
    info = sd.read_bytes((DOCS / "knight-release.html").read_bytes(), name="r.html")
    texts = [s["text"] for s in info["sentences"]]
    assert info["type"] == "html"
    assert "Washington D.C., Oct. 16, 2013." in texts      # a date is a receipt
    assert "Knight agreed to pay $12 million to settle the charges." in texts
    assert not any("Newsroom" in t or "last reviewed" in t for t in texts)


@pytest.mark.parametrize("text, want", [
    ("Knight Capital Americas LLC, Inc. was a broker. It traded thousands of stocks.",
     ["Knight Capital Americas LLC, Inc. was a broker.", "It traded thousands of stocks."]),
    ("See U.S. v. Smith, No. 12-cv-1, at page 4. The court agreed with the order.",
     ["See U.S. v. Smith, No. 12-cv-1, at page 4.", "The court agreed with the order."]),
    ("The order was signed by J. Smith on the day. It took effect at once.",
     ["The order was signed by J. Smith on the day.", "It took effect at once."]),
])
def test_abbreviations_do_not_end_a_sentence(text, want):
    assert [s["text"] for s in sd.sentences_of([text])] == want


def test_a_sentence_carried_onto_the_next_page_counts_on_the_first():
    got = sd.sentences_of(["The firm lost more than four hundred", "million dollars that "
                           "morning. The next day it was rescued by others."])
    assert got[0]["page"] == 1 and got[0]["text"].endswith("that morning.")
    assert got[1]["page"] == 2


def test_a_scan_and_a_broken_file_say_why_they_were_not_read():
    scan = sd.read_bytes(tiny_pdf([[]]), name="scan.pdf")
    assert scan["sentences"] == [] and "scan" in scan["why"]
    broken = sd.read_bytes(b"%PDF-1.4 not really", name="broken.pdf")
    assert broken["sentences"] == [] and "could not be read" in broken["why"]


def test_gather_reads_the_best_kinds_first_and_keeps_its_ids(tmp_path, settings):
    story = {"documents": [
        {"url": "https://court.example/fixture/judgment.pdf", "kind": "court"},
        {"url": "https://www.sec.gov/fixture/order.pdf", "kind": "regulator"},
        {"url": "https://doj.example/fixture/gone", "kind": "prosecutor"},
    ]}
    pdf = (DOCS / "knight-order.pdf").read_bytes()
    calls: list[str] = []

    def fetcher(url):
        calls.append(url)
        if url.endswith("gone"):
            return None, "", "404 from the site"
        return pdf, "application/pdf", ""

    got = sd.gather(story, tmp_path, settings, fetcher=fetcher)
    by_id = {d["id"]: d for d in got["documents"]}
    assert by_id["D1"]["kind"] == "regulator" and by_id["D1"]["status"] == "read"
    assert by_id["D2"]["kind"] == "prosecutor" and by_id["D2"]["why"] == "404 from the site"
    assert by_id["D3"]["kind"] == "court"
    assert (tmp_path / by_id["D1"]["file"]).read_bytes() == pdf
    # A second read fetches nothing it has, and the numbers stay put.
    calls.clear()
    again = sd.gather(story, tmp_path, settings, fetcher=fetcher)
    assert calls == [] and [d["id"] for d in again["documents"]] == ["D1", "D2", "D3"]


def test_a_dropped_pdf_joins_and_dropping_it_again_replaces_it(tmp_path):
    pdf = (DOCS / "knight-order.pdf").read_bytes()
    first = sd.add_upload(tmp_path, "order.pdf", pdf)
    assert first["id"] == "D1" and first["status"] == "read"
    second = sd.add_upload(tmp_path, "order.pdf", tiny_pdf([["A newer reading of the "
                                                             "same order, page one."]]))
    assert second["id"] == "D1"
    other = sd.add_upload(tmp_path, "release.html",
                          (DOCS / "knight-release.html").read_bytes())
    assert other["id"] == "D2"
    assert [d["id"] for d in sd.documents(tmp_path)] == ["D1", "D2"]


def test_the_writer_is_handed_numbered_receipts(tmp_path):
    sd.add_upload(tmp_path, "order.pdf", (DOCS / "knight-order.pdf").read_bytes())
    block = sd.prompt_block(tmp_path)
    assert "D1.5" in block and "p.2" in block and "$460 million" in block
    assert len(sd.brief_block(tmp_path)) <= len(block)
    assert "$12 million" in sd.find_sentence(tmp_path, "D1.6")
    assert sd.find_sentence(tmp_path, "D9.1") == ""
    assert sd.summary(tmp_path)["sentences"] == 8


# ------------------------------------------------------- the story's code


@pytest.mark.parametrize("name, year, code", [
    ("Knight Capital Group", 2012, "IMP-KNIGHT12"),
    ("Long-Term Capital Management", 1998, "IMP-LTCM98"),
    ("2010 flash crash", 2010, "IMP-FLASH10"),
    ("Archegos Capital Management", 2021, "IMP-ARCHEGOS21"),
])
def test_a_story_is_filed_under_a_code_no_ticker_can_have(name, year, code):
    got = im.story_code({"name": name, "year": year})
    assert got == code and im.is_story_code(got) and len(got) <= 14


def test_a_story_is_found_by_number_id_or_name(every_list):
    im.refresh(every_list)
    first = im.shown(every_list)[0]
    assert im.find(every_list, "1")["id"] == first["id"]
    assert im.find(every_list, first["id"])["id"] == first["id"]
    assert im.find(every_list, "knight")["name"] == "Knight Capital Group"
    assert im.find(every_list, "999") is None
    assert im.find(every_list, "no such story") is None


# ------------------------------------------------------------- the flow


def test_starting_reads_the_documents_and_writes_the_angle_prompt(core, every_list):
    ws = _knight(core)
    assert ws.ticker == "IMP-KNIGHT12" and ws.is_implosion() and ws.lane() == "long"
    assert ws.awaiting_angle()
    docs = sd.documents(ws.path)
    assert [d["status"] for d in docs] == ["read", "read"]
    prompt = (ws.path / "prompt_implosion_angle.md").read_text(encoding="utf-8")
    assert "{{" not in prompt
    assert "Knight Capital Group" in prompt and "D1.5" in prompt
    assert "a MAP, not a receipt" in prompt
    # Off the list he picks from; found again by name.
    assert "Knight Capital Group" not in [s["name"] for s in im.shown(every_list)]
    assert im.find(every_list, "Knight")["name"] == "Knight Capital Group"


def test_no_story_says_how_and_lists_them(core):
    reply = core.start_implosion(CHAT, [])
    assert "Usage: /new implosion" in reply.text
    assert "No story matches" in core.start_implosion(CHAT, ["zzz"]).text


def test_the_command_is_registered():
    from bot.commands import COMMANDS

    names = {c.name for c in COMMANDS}
    assert "new implosion" in names


def test_picking_an_angle_writes_the_implosion_writer(core):
    ws = _knight(core)
    reply = core.angle_pick(CHAT, ws.ticker, ws.workdate, "2")
    assert "Angle locked for Knight Capital Group" in reply.text
    prompt = (ws.path / "prompt_implosion_write.md").read_text(encoding="utf-8")
    assert "{{" not in prompt
    assert "D1.5" in prompt and "the-trick" in prompt and "the-bill" in prompt
    # The stock long's types the implosion has no use for are not offered.
    assert "| valuation |" not in prompt and "\nvaluation " not in prompt
    assert not (ws.path / "prompt_long_write.md").exists()


def test_a_workbook_is_refused_and_a_pdf_joins(core, fixtures_dir):
    ws = _knight(core)
    xlsx = (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()
    assert "no workbook" in core.handle_upload(CHAT, "dennis_data.xlsx", xlsx).text
    assert not (ws.path / "dennis_data.xlsx").exists()
    reply = core.handle_upload(CHAT, "judgment.pdf", tiny_pdf(
        [["The court entered final judgment on the consent of the parties."]]))
    assert "D3" in reply.text, reply.text
    assert [d["id"] for d in sd.documents(ws.path)] == ["D1", "D2", "D3"]


IMPLOSION_SCRIPT = """\
At nine thirty on the first of August twenty twelve, a computer in New Jersey woke up with an idea. [PLATE: big-number-l1-16x9 | kicker=ORDERS SENT | value=4M+ | label=in forty-five minutes | caption=SEC order, D1.3] By lunch the idea had cost more than four hundred and sixty million dollars. To understand how, we have to go back.

Knight made markets. [PLATE: definition-16x9 | kicker=THE WORD OF THE DAY | term=Market making | body=You stand in the middle and buy at ten and sell at ten oh one. | example=A cent, a million times a day.] It looks smart because it is smart, right up until the part where it is not.

The trick was a server nobody updated. [PLATE: flow-16x9 | kicker=WHAT WENT WRONG | input=New code | box-1=Seven servers | box-2=One server | box-3=Old flag | output=Every order | arrow-1=. | arrow-2=. | arrow-3=. | arrow-4=. | caption=One of eight] Seven of eight servers got the new code. The eighth got a party.

The bill came in October twenty thirteen. [PLATE: quote-pull-16x9 | body=The Respondent agreed to pay a civil money penalty of $12 million. | attribution=The SEC's order | source=D1.6] Twelve million dollars, without admitting or denying the findings, which is the legal way of saying "anyway".

[PLATE: closing-16x9 | kicker=THE CLOSE | line-1=The bug was not the story. | line-2=The missing check was. | line-3=I have also skipped a check. | date-label=Order | date=16 Oct 2013] The bug was not the story. The missing check was. I don't do endings: this is the end.

=== CHAPTERS ===
00:00 cold-open | a computer with an idea
00:20 how-the-money-is-made | a cent a million times
00:40 the-trick | the eighth server
01:00 the-bill | twelve million, anyway
01:20 resigned-close | the missing check

=== CONFESSION ===
epistemic | I still could not tell you what the old flag was for.
"""


def test_an_implosion_script_needs_no_workbook_and_no_price(core):
    ws = _knight(core)
    core.angle_pick(CHAT, ws.ticker, ws.workdate, "1")
    reply = core.intake_script(CHAT, IMPLOSION_SCRIPT, from_page=True)
    assert ws.load_long() is not None, reply.text
    report = json.loads((ws.path / "report_long.json").read_text(encoding="utf-8"))
    blocking = " ".join(report.get("blocking") or [])
    assert "workbook" not in blocking.lower() and "dennis_data" not in blocking
    assert "price" not in blocking.lower(), blocking


def test_the_freshness_gate_is_skipped_and_says_why(core):
    from pipeline.gates import run_gates
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(IMPLOSION_SCRIPT, "IMP-KNIGHT12", core.settings)
    report = run_gates(script, core.settings, data=None, format_name="implosion")
    assert report.ran["freshness"] == "skipped:an implosion has no workbook"


def test_a_price_chart_or_a_product_shot_is_refused(core):
    ws = _knight(core)
    core.angle_pick(CHAT, ws.ticker, ws.workdate, "1")
    bad = IMPLOSION_SCRIPT.replace(
        "Knight made markets.",
        "Knight made markets. [CHART: price] [IMG: Knight Capital office]")
    reply = core.intake_script(CHAT, bad, from_page=True)
    assert "CHART" in reply.text and "IMG" in reply.text, reply.text


def test_prices_stand_aside_for_a_story_code(settings, monkeypatch):
    import httpx

    from pipeline.prices import get_price_history

    def no_network(*a, **k):
        raise AssertionError("a story code reached the network")

    monkeypatch.setattr(httpx, "get", no_network)
    monkeypatch.setattr(httpx.Client, "get", no_network)
    live = settings.model_copy(update={"mock_mode": False})
    series = get_price_history("IMP-KNIGHT12", live)
    assert series.degraded


# ------------------------------------------------------- the card and the page


def test_the_card_says_implosion_and_needs_no_workbook(core):
    from pipeline.video_state import card_text, video_state

    ws = _knight(core)
    st = video_state(core.settings, ws)
    assert st.implosion and st.documents == 2 and st.story == "Knight Capital Group"
    step, action = st.next_step()
    assert "prompt_implosion_angle.md" in step and action == "angle"
    text = card_text(st)
    assert "IMPLOSION" in text and "documents ✅ 2 read" in text
    assert "dennis_data" not in text


def test_the_page_shows_the_documents_on_the_data_step(core):
    from bot.panel import Panel
    from bot.panel_views import video_view

    ws = _knight(core)
    panel = Panel(core, loop=None)
    view = video_view(panel, ws.ticker, ws.workdate)
    assert view["now"] == "angle"
    data = video_view(panel, ws.ticker, ws.workdate, step="data")["data"]
    assert data["implosion"] and data["read"] == 2
    assert [d["id"] for d in data["documents"]] == ["D1", "D2"]
    assert data["story"]["name"] == "Knight Capital Group"
    angle = video_view(panel, ws.ticker, ws.workdate, step="angle")["angle"]
    assert angle["prompt"]["name"] == "prompt_implosion_angle.md"
    assert angle["prompt"]["url"]


def test_an_approved_implosion_queues_its_final(core):
    """The final's checks ask for prices and a workbook nowhere: the room's
    board and monitor stand aside for a story code, and so does the price
    check before the money is spent."""
    from pipeline.models import JobKind

    ws = _knight(core)
    core.angle_pick(CHAT, ws.ticker, ws.workdate, "1")
    core.intake_script(CHAT, IMPLOSION_SCRIPT, from_page=True)
    sha = ws.load_long().content_sha()[:8]
    reply = core.approve("long", ws.ticker, ws.workdate, sha)
    assert ws.is_approved("long"), reply.text
    kind, text, _ = core.render_request(f"{ws.ticker}@{ws.workdate}")
    assert kind is JobKind.RENDER_LONG, text


def test_the_room_letters_the_case_not_a_ticker():
    import datetime as dt

    from pipeline.room_writing import filings

    got = filings("IMP-KNIGHT12B", dt.date(2026, 11, 7))
    assert got["filing"] == "IN THE MATTER OF\nKNIGHT"
    assert "10-Q" not in got["deskstack-top"] and "KNIGHT" in got["deskstack-top"]
    assert "IMP-" not in " ".join(got.values())
    assert im.code_word("IMP-LTCM98") == "LTCM"


def test_the_upload_package_names_the_story_and_its_documents(core):
    from pipeline.parser_long import parse_long_script
    from pipeline.publish import build_package

    script, _ = parse_long_script(IMPLOSION_SCRIPT, "IMP-KNIGHT12", core.settings)
    pkg = build_package(script, core.settings, ticker="IMP-KNIGHT12",
                        runtime_min=14, story="Knight Capital Group")
    text = pkg.render_text()
    assert pkg.titles[0].startswith("Knight Capital Group — ")
    assert "How Knight Capital Group blew up, in 14 minutes" in pkg.titles
    assert "$IMP" not in text and "company's filings" not in text
    assert "documents shown on screen" in pkg.description
    assert "00:00 a computer with an idea" in pkg.description
    assert "IMP-" not in pkg.thumbnail_prompt
    assert "Knight Capital Group" in pkg.thumbnail_prompt
    # Without a name (the title check reads it off the script alone).
    bare = build_package(script, core.settings)
    assert bare.titles[0].startswith("Knight — ")


def test_the_writers_titles_name_the_story(core):
    from pipeline.parser_long import parse_long_script
    from pipeline.publish import build_package

    with_titles = IMPLOSION_SCRIPT.replace("=== CONFESSION ===", (
        "=== TITLES ===\n"
        "The computer that lost $460 million before lunch | By lunch the idea "
        "had cost more than four hundred and sixty million dollars.\n"
        "Thumbnail: before lunch\n\n=== CONFESSION ==="))
    script, _ = parse_long_script(with_titles, "IMP-KNIGHT12", core.settings)
    pkg = build_package(script, core.settings, ticker="IMP-KNIGHT12",
                        story="Knight Capital Group", fmt="long")
    assert pkg.titles_from_writer, pkg.title_notes
    assert pkg.titles[0] == "The computer that lost $460 million before lunch"
    assert "IMP-" not in pkg.thumbnail_prompt
