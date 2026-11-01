"""The first real render (RBLX short, 1 Nov 2026) and the RDDT long after it:
what went wrong on Valentin's box, each pinned so it stays fixed.

- the bot sat on "saving the video" while it drew covers in Blender;
- a refused news page was read as a browser and the ad blurb taken as the
  story;
- Wikimedia's first result (the Roblox logo) was blown up full screen, with
  a caption;
- [QUIET] came out as a broken whisper (retired: test_direction);
- the workbook's operating cash flow was one quarter behind its labels;
- the call's outlook warning never reached the writer;
- Gemma timed out reading the filings, and the angle prompt went out
  without them.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------- the save step

def test_the_cover_is_its_own_stage_and_saved_is_not_still_saving():
    from pipeline import jobs

    assert jobs.STAGE_SPAN["cover"][1] <= jobs.STAGE_SPAN["delivery"][0]
    assert "cover" in jobs.STAGE_WORDS["cover"].lower()
    assert "saved" in jobs.STAGE_WORDS["delivered"].lower()


def test_a_still_that_runs_out_of_time_stops_the_others(settings, tmp_path,
                                                        monkeypatch):
    """Four stills at twelve minutes each was the 'saving' hang: one that
    runs out now costs STILL_TIMEOUT_S, and the rest go without him."""
    import sys
    from types import SimpleNamespace

    from pipeline import dennis3d
    from pipeline.render_common import RenderError

    slow = tmp_path / "slow_worker.py"
    slow.write_text("import sys, time\nfor line in sys.stdin:\n    time.sleep(60)\n",
                    encoding="utf-8")
    monkeypatch.setattr(dennis3d, "WORKER", slow)
    monkeypatch.setattr(dennis3d, "STILL_TIMEOUT_S", 0.5)
    monkeypatch.setattr(settings, "dennis_3d_python", sys.executable)
    room = SimpleNamespace(key="room/desk-front-16x9", author="room3d")
    p = dennis3d.Performer(settings, cache=tmp_path / "cache")
    try:
        t0 = time.monotonic()
        with pytest.raises(RenderError, match="still"):
            p.still(room, (64, 64), seed="A")
        assert time.monotonic() - t0 < 30
        assert p.gave_up
        t1 = time.monotonic()
        with pytest.raises(RenderError, match="ran out of time"):
            p.still(room, (64, 64), seed="B")
        assert time.monotonic() - t1 < 2, "the second still was attempted"
    finally:
        p.close()


# ----------------------------------------------------------- the news page

def test_the_bot_names_itself_without_his_email():
    from pipeline import news_page

    assert "@" not in news_page.USER_AGENT
    assert "stockanalysis.com" in news_page.NO_BROWSER_HOSTS


def test_a_page_s_plug_for_itself_is_not_taken_as_the_story():
    from pipeline.news_page import read_page

    html = """<html><head><meta property="og:site_name" content="TipRanks">
    <title>Roblox sees Q4 bookings slow as GTA 6 launch looms - TipRanks.com</title>
    </head><body><h1>Roblox sees Q4 bookings slow as GTA 6 launch looms - TipRanks.com</h1>
    <p>Discover the ultimate source for stock research with a free trial of our
    premium plan, trusted by millions of investors around the world today.</p>
    <p>Roblox said fourth-quarter bookings growth would slow as the launch of
    GTA 6 draws players away, sending the shares lower after the report.</p>
    </body></html>"""
    page = read_page(html)
    assert page["title"] == "Roblox sees Q4 bookings slow as GTA 6 launch looms"
    assert page["body"].startswith("Roblox said fourth-quarter bookings")


# ------------------------------------------------------------- the picture

def test_a_logo_is_never_the_company_s_photo():
    from pipeline.broll import photos_only

    got = photos_only([
        {"title": "File:Roblox logo 2022.svg", "width": 2000, "height": 600,
         "mime": "image/svg+xml"},
        {"title": "File:Roblox wordmark.png", "width": 3000, "height": 900,
         "mime": "image/png"},
        {"title": "File:Tiny office.jpg", "width": 640, "height": 480,
         "mime": "image/jpeg"},
        {"title": "File:Roblox headquarters San Mateo.jpg", "width": 4000,
         "height": 3000, "mime": "image/jpeg"},
    ])
    assert [r["title"] for r in got] == ["File:Roblox headquarters San Mateo.jpg"]


def test_a_flat_graphic_fails_the_last_look_and_a_photo_passes(tmp_path):
    import numpy as np

    from pipeline.broll import looks_like_a_photo

    flat = Image.new("RGB", (400, 300), (220, 30, 30))
    flat.paste((255, 255, 255), (100, 100, 300, 200))
    flat.save(tmp_path / "logo.png")
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    Image.fromarray(noise).save(tmp_path / "photo.jpg")
    assert not looks_like_a_photo(tmp_path / "logo.png")
    assert looks_like_a_photo(tmp_path / "photo.jpg")


def test_the_short_s_picture_carries_no_words():
    for name in ("short.json", "earnings.json"):
        shots = json.loads((ROOT / "templates" / "shots" / name).read_text(encoding="utf-8"))
        found = [s for s in _walk(shots) if s.get("id") == "the-picture"
                 or s.get("name") == "the-picture" or s.get("key") == "the-picture"]
        assert found, f"{name} has no the-picture shot"
        for s in found:
            assert s.get("text") == [], f"{name}: the picture has words on it"


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# ------------------------------------------------------------- the workbook

def _pack(ocf_m: list[float]) -> dict:
    """The site's quarters, newest first, as stockanalysis gives them."""
    periods = [("Q3 2025", "2025-09-30"), ("Q2 2025", "2025-06-30"),
               ("Q1 2025", "2025-03-31"), ("Q4 2024", "2024-12-31"),
               ("Q3 2024", "2024-09-30")]
    return {"quarterly": {
        "periods": [{"label": lb, "end": e} for lb, e in periods],
        "rows": {"Operating Cash Flow": ocf_m}}}


def test_a_cash_flow_row_one_quarter_behind_is_moved_back(settings):
    """CapIQ's as-filed OCF waits for the 10-Q: in earnings week each column
    held the quarter before's figure, and FCF mixed two quarters."""
    from pipeline import site_pack
    from pipeline.models import CompanyData

    labels = ["Q3 FY24", "Q4 FY24", "Q1 FY25", "Q2 FY25", "Q3 FY25"]
    site = [546.0, 349.0, 443.0, 184.0, 248.0]          # Q3 25 .. Q3 24
    lagged = [200e6, 248e6, 184e6, 443e6, 349e6]        # each one quarter late
    data = CompanyData(quarter_labels=labels, quarters={
        "operating_cf": list(lagged), "capex": [-50e6] * 5,
        "revenue": [1e9] * 5, "fcf": [o - 50e6 for o in lagged],
        "fcf_margin": [(o - 50e6) / 1e9 * 100 for o in lagged]})
    said = site_pack.realign_lagged_rows(data, _pack(site))
    assert said and "one quarter behind" in said[0]
    assert data.quarters["operating_cf"] == [248e6, 184e6, 443e6, 349e6, None]
    assert data.quarters["fcf"][:4] == [198e6, 134e6, 393e6, 299e6]
    assert data.quarters["fcf_margin"][0] == pytest.approx(19.8)


def test_a_row_that_matches_its_own_quarter_is_left_alone(settings):
    from pipeline import site_pack
    from pipeline.models import CompanyData

    labels = ["Q3 FY24", "Q4 FY24", "Q1 FY25", "Q2 FY25", "Q3 FY25"]
    right = [248e6, 184e6, 443e6, 349e6, 546e6]
    data = CompanyData(quarter_labels=labels,
                       quarters={"operating_cf": list(right)})
    assert site_pack.realign_lagged_rows(
        data, _pack([546.0, 349.0, 443.0, 184.0, 248.0])) == []
    assert data.quarters["operating_cf"] == right


def test_the_template_asks_for_the_period_keyed_cash_flow():
    import zipfile

    with zipfile.ZipFile(ROOT / "templates" / "dennis_data_template.xlsx") as z:
        xml = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                      if n.endswith(".xml"))
    assert "IQ_CASH_OPER_CS" not in xml
    assert "IQ_CASH_OPER" in xml
    assert "v3.3" in xml


def test_not_meaningful_and_formula_errors_are_quietly_missing(caplog):
    from pipeline.company_data import _coerce

    with caplog.at_level(logging.WARNING, logger="pipeline.company_data"):
        assert _coerce("pe_ratio", "NM") is None
        assert _coerce("pe_ratio", "nm") is None
        assert _coerce("revenue_growth", "#VALUE!") is None
        assert _coerce("revenue_growth", "#DIV/0!") is None
    assert not caplog.records, [r.getMessage() for r in caplog.records]
    with caplog.at_level(logging.WARNING, logger="pipeline.company_data"):
        assert _coerce("company_name", "#CIQINACTIVE") is None
    assert caplog.records, "the add-in failing is still worth a warning"


# ------------------------------------------------------------- the call

def test_a_speaker_s_title_is_read_past_the_page_s_markers():
    from pipeline.stockanalysis import parse_transcript

    html = """<h1>Roblox Q3 2026 Earnings Call</h1><p>Oct 30, 2026</p>
    <div class="text-lg font-bold text-default">Naveen Chopra</div><!--[0-->
    <div class="text-sm italic text-muted">Chief Financial Officer</div><!--]-->
    <p><span class="transcript-sentence">We expect bookings growth to moderate
    in the fourth quarter as a major game release competes for time.</span></p>"""
    turns = parse_transcript(html)["turns"]
    assert turns[0]["role"] == "Chief Financial Officer"


_TURNS = [
    {"speaker": "Operator", "role": "", "text": "Welcome to the call."},
    {"speaker": "Ana IR", "role": "VP Investor Relations",
     "text": "Today's remarks contain forward-looking statements and actual "
             "results may differ materially from those described."},
    {"speaker": "Dave CEO", "role": "Chief Executive Officer",
     "text": "We had a record quarter with daily active users up 20% to 111 "
             "million. Engagement hours grew faster than the industry again."},
    {"speaker": "Nat CFO", "role": "Chief Financial Officer",
     "text": "For the fourth quarter we expect bookings growth to moderate to "
             "around 30%, largely due to the release of a major console game "
             "competing for players' time. We expect operating cash flow of "
             "about $400 million in the fourth quarter."},
    {"speaker": "Sam Analyst", "role": "Analyst, Big Bank",
     "text": "Can you say more about how much the game release will impact "
             "engagement in the fourth quarter and into next year?"},
]


def test_management_s_outlook_and_its_reason_reach_the_writer():
    from pipeline import site_pack

    got = site_pack.outlook_lines(_TURNS, 2400)
    said = [g["text"] for g in got]
    assert any("due to the release of a major console game" in s for s in said)
    assert all(g["speaker"] in ("Dave CEO", "Nat CFO") for g in got), \
        "an analyst's question is not management's outlook"
    assert not any("forward-looking" in s for s in said)


def test_the_safe_harbor_is_never_a_passage(settings):
    from pipeline import site_pack

    windows = site_pack._windows(_TURNS)
    assert windows and not any("forward-looking" in w["text"] for w in windows)


def test_the_short_prompt_says_the_outlook_is_the_move(tmp_path):
    from pipeline import site_pack

    site_pack._save(tmp_path, {"call": {
        "title": "Earnings Call: Q3 2026", "date": "2026-10-30",
        "turns": _TURNS, "passages": [], "summary": "Bookings up."}})
    block = site_pack.call_block(tmp_path, "short")
    assert "WHAT MANAGEMENT SAID COMES NEXT" in block
    assert "due to the release of a major console game" in block
    assert "THE OUTLOOK IS THE MOVE" in block


# ------------------------------------------------------------- the voice

def test_the_new_tags_are_in_the_writer_s_vocabulary(settings):
    from bot.prompts import delivery_vocabulary
    from pipeline.direction import DIRECTIONS
    from pipeline.models import DELIVERY_TAG_TYPES, TagType

    vocab = delivery_vocabulary()
    for tag in (TagType.ANNOYED, TagType.IMPRESSED, TagType.NERVOUS,
                TagType.CLEAR_THROAT, TagType.GULP):
        assert tag in DELIVERY_TAG_TYPES
        assert tag in DIRECTIONS
        assert f"[{tag.value}]" in vocab, f"[{tag.value}] is not offered"


def test_benjamin_s_lines_go_to_every_writing_prompt(settings):
    from bot.prompts import benjamin_lines, payload_tokens

    for fmt in ("short", "long_write", "update", "headline"):
        assert "{{benjamin_lines}}" in payload_tokens(fmt)
    for name in ("short", "long_write", "update", "headline"):
        text = (ROOT / "templates" / f"master_prompt_{name}.md").read_text(encoding="utf-8")
        assert "{{benjamin_lines}}" in text, name
    block = benjamin_lines(settings)
    assert "never a line" in block


# ------------------------------------------------------------- the local model

def test_a_background_pass_asks_the_model_not_to_think(settings, monkeypatch):
    import pipeline.llm as llm

    live = settings.model_copy(update={"mock_mode": False,
                                       "llm_provider_order": "ollama"})
    seen: list[dict] = []
    monkeypatch.setattr(llm, "_post", lambda url, payload, headers, timeout: (
        seen.append(payload) or {"message": {"content": "ok"}}))
    assert llm.chat("q", live, purpose="filing-brief-section") == "ok"
    assert seen[-1]["think"] is False
    thinking = live.model_copy(update={"ollama_think_passes": True})
    assert llm.chat("q", thinking, purpose="skeptic") == "ok"
    assert "think" not in seen[-1]
    llm.reset_llm_calls()


def test_an_ollama_that_refuses_think_is_asked_again_without_it(settings,
                                                               monkeypatch):
    import pipeline.llm as llm

    class _Resp:
        status_code = 400

        def json(self):
            return {"error": "invalid option: think"}

    class _Refused(Exception):
        response = _Resp()

    live = settings.model_copy(update={"mock_mode": False,
                                       "llm_provider_order": "ollama"})
    calls: list[dict] = []

    def _post(url, payload, headers, timeout):
        calls.append(payload)
        if "think" in payload:
            raise _Refused("400")
        return {"message": {"content": "answered"}}

    monkeypatch.setattr(llm, "_post", _post)
    assert llm.chat("q", live, purpose="filing-brief-section") == "answered"
    assert len(calls) == 2 and "think" not in calls[1]
    llm.reset_llm_calls()


def test_three_empty_parts_in_a_row_stop_the_reading(settings, monkeypatch):
    """A model that has stopped answering is not asked twenty more times."""
    from types import SimpleNamespace

    import pipeline.llm as llm
    from pipeline import filing_brief as fb

    asked = []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: asked.append(1) or None)
    sections = [{"title": f"S{i}", "text": "x" * 500} for i in range(8)]
    counters: dict = {}
    ref = SimpleNamespace(form="10-K", period="2025", filed="2026-02-01")
    fb._summarise_sections(ref, sections, settings, counters)
    assert len(asked) == fb.MISSES_TO_STOP
    assert counters["gave_up"] and counters["parts_done"] == fb.MISSES_TO_STOP


# --------------------------------------------- the upload waits for the filings

@pytest.fixture
def core(settings):
    from bot.handlers import BotCore

    c = BotCore(settings.model_copy(update={"filing_brief_wait_s": 0.6,
                                            "filing_brief_max_wait_s": 20.0}))
    yield c


def _reading(core, ws, steps: int, step_s: float, counters: dict):
    def _run():
        for i in range(steps):
            time.sleep(step_s)
            counters["parts_done"] = i + 1
            counters["parts_total"] = steps
            counters["filings"], counters["filing"] = 4, 1
    core._filing_progress[core._filing_read_key(ws)] = counters
    return core.filing_reader.submit(f"{ws.ticker} {ws.workdate}", _run)


def test_a_reading_that_keeps_moving_is_waited_out(core, monkeypatch):
    """RDDT: the prompt went out without the brief after ten minutes flat
    while the reading was still going. Now the wait lasts as long as parts
    keep finishing, past FILING_BRIEF_WAIT_S, and says how far it got."""
    import bot.handlers as handlers
    from pipeline.workspace import Workspace

    monkeypatch.setattr(handlers, "PROGRESS_EVERY_S", 0.0)
    ws = Workspace(core.settings, "RDDT", "2026-11-01").create()
    fut = _reading(core, ws, steps=8, step_s=0.2, counters={})
    notes: list[str] = []
    t0 = time.monotonic()
    core._wait_for_reading(ws, fut, notes.append)
    assert time.monotonic() - t0 > core.settings.filing_brief_wait_s
    assert fut.done()
    assert notes and "reading the filings" in notes[-1]
    assert "parts read" in notes[-1]


def test_a_stalled_reading_lets_the_prompt_go(core):
    from pipeline.workspace import Workspace

    ws = Workspace(core.settings, "RDDT", "2026-11-02").create()
    stuck = threading.Event()
    core._filing_progress[core._filing_read_key(ws)] = {}
    fut = core.filing_reader.submit("RDDT stuck", lambda: stuck.wait(10))
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        core._wait_for_reading(ws, fut, None)
    assert time.monotonic() - t0 < 5
    stuck.set()
    fut.result(timeout=10)
