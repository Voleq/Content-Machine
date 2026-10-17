"""Findings from the full review of the research and publishing code.

Each test names what a viewer or the operator would have seen go wrong.
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest


def _live(settings, **kw):
    return settings.model_copy(update={"mock_mode": False, **kw})


def test_a_backend_that_fails_any_way_keeps_the_paid_render(settings,
                                                           monkeypatch,
                                                           tmp_path):
    """A missing Drive credentials file failed the job after the render."""
    from pipeline import delivery

    class Drive:
        def __init__(self, settings):
            pass

        def upload(self, *a, **kw):
            raise FileNotFoundError("/nope/credentials.json")

    monkeypatch.setattr(delivery, "GDriveBackend", Drive)
    video = tmp_path / "final.mp4"
    video.write_bytes(b"mp4")
    got = delivery.deliver(video, "EXMPL", "2026-10-17",
                           _live(settings, delivery_backend="gdrive"))
    assert got.backend == "local"
    assert "gdrive delivery failed" in got.note


def test_alert_hours_of_0_to_24_are_never_quiet(settings):
    from pipeline.alerts import in_quiet_hours

    s = settings.model_copy(update={"alert_start_hour": 0,
                                    "alert_end_hour": 24,
                                    "alert_weekends": True})
    for hour in (3, 12, 23):
        assert not in_quiet_hours(s, datetime(2026, 10, 14, hour))


def test_a_filing_alerts_once_not_every_cooldown(settings):
    from pipeline.alerts import Alert, AlertLog

    log_ = AlertLog(settings)
    t0 = datetime(2026, 10, 14, 13, tzinfo=timezone.utc)
    filed = Alert(ticker="EXMPL", kind="filing", headline="filed an 8-K",
                  magnitude=2.0, ident="8k:0001")
    assert log_.should_send(filed, t0)
    log_.record(filed, t0)
    later = t0 + timedelta(hours=4)
    assert not log_.should_send(filed, later)
    # A move in between does not make the filing new again.
    move = Alert(ticker="EXMPL", kind="move", headline="up 9%", magnitude=9)
    log_.record(move, later)
    assert not log_.should_send(filed, later + timedelta(hours=4))
    # A different filing is news.
    other = Alert(ticker="EXMPL", kind="filing", headline="filed an 8-K",
                  magnitude=2.0, ident="8k:0002")
    assert log_.should_send(other, later + timedelta(hours=4))


def test_a_print_days_gone_is_not_announced(settings, core):
    from pipeline.alerts import EarningsCalendar

    cal = EarningsCalendar(settings)
    cal.set("EXMPL", "2026-09-01", "amc")
    assert cal.due_alerts(date(2026, 10, 16)) == []
    cal.set("EXMPL", "2026-10-15", "amc")
    assert cal.due_alerts(date(2026, 10, 16))
    assert "has passed" in core.earnings_command(
        ["EXMPL", (date.today() - timedelta(days=3)).isoformat()]).text


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def test_a_reread_angle_leaves_no_old_shots(settings, monkeypatch, tmp_path):
    from pipeline import filings

    ws = tmp_path / "ws"
    ws.mkdir()
    for n in (1, 2, 3):
        (ws / f"filing_{n:02d}.png").write_bytes(b"png")
    (ws / "broker-pnl.png").write_bytes(b"mine")
    monkeypatch.setattr(filings, "resolve_filing", lambda *a, **k: None)
    assert filings.auto_filings("EXMPL", "angle", ws, settings) == []
    assert sorted(p.name for p in ws.glob("*.png")) == ["broker-pnl.png"]


def test_nested_filing_text_is_read_once():
    from pipeline.filings import segment_filing

    html = ("<html><body><h2>Item 7. Management's Discussion and Analysis</h2>"
            "<table><tr><td><p>Revenue rose eleven percent.</p></td></tr></table>"
            "<ul><li><p>Margins held at forty-one percent.</p></li></ul>"
            "<table><tr><td><div><span>Cash fell to two hundred million."
            "</span></div></td></tr></table></body></html>")
    text = " ".join(s["text"] for s in segment_filing(html))
    for said in ("Revenue rose eleven percent.",
                 "Margins held at forty-one percent.",
                 "Cash fell to two hundred million."):
        assert text.count(said) == 1, text


def test_a_year_ago_quarter_is_the_same_quarter():
    from pipeline.filings import FilingRef, _same_quarter_a_year_earlier

    def ref(acc, period):
        return FilingRef(ticker="X", cik="1", form="10-Q", accession=acc,
                         primary_doc="d.htm", url="u", period=period)

    now = ref("a", "2026-09-30")
    assert _same_quarter_a_year_earlier(
        now, [now, ref("b", "2025-06-30"), ref("c", "2025-03-31")]) is None
    shifted = ref("d", "2025-09-27")
    assert _same_quarter_a_year_earlier(now, [now, shifted]) is shifted


def test_a_verified_sentence_has_no_heading_glued_on():
    from pipeline.filing_brief import find_sentence

    got = find_sentence(
        "\n## Risk Factors\nInvesting in our common stock involves a high "
        "degree of risk. You should consider it.",
        "Investing in our common stock involves a high degree of risk.")
    assert got == "Investing in our common stock involves a high degree of risk."


def test_subtitle_cues_never_overlap():
    from pipeline.models import WordTimestamp
    from pipeline.publish import group_cues

    words, at = [], 0
    for word, start, end in (("Cheap.", 0.0, 0.4), ("Or", 0.55, 0.7),
                             ("a", 0.7, 0.8), ("trap?", 0.8, 1.3)):
        words.append(WordTimestamp(word=word, start=start, end=end,
                                   char_start=at, char_end=at + len(word)))
        at += len(word) + 1
    cues = group_cues(words)
    assert len(cues) == 2
    assert cues[0][1] <= cues[1][0]


def test_upload_retries_are_per_chunk(settings, monkeypatch, tmp_path):
    """One hiccup in each of three chunks aborted a two-retry upload."""
    from pipeline import youtube

    http = types.ModuleType("googleapiclient.http")
    http.MediaFileUpload = lambda *a, **k: object()
    pkg = types.ModuleType("googleapiclient")
    pkg.http = http
    monkeypatch.setitem(sys.modules, "googleapiclient", pkg)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http)
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)

    steps = iter(["err", (0.33, None), "err", (0.66, None), "err",
                  (None, {"id": "vid1"})])

    class Status:
        def __init__(self, p):
            self.p = p

        def progress(self):
            return self.p

    class Request:
        def next_chunk(self):
            step = next(steps)
            if step == "err":
                raise ConnectionResetError("reset")
            p, response = step
            return (Status(p) if p else None), response

    class Videos:
        def insert(self, **kw):
            return Request()

    class Api:
        def videos(self):
            return Videos()

    client = youtube.YouTubeClient.__new__(youtube.YouTubeClient)
    client.settings = settings.model_copy(update={"youtube_upload_retries": 2})
    client._youtube = Api()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert client.upload(video, {}) == "vid1"


def test_a_failing_fred_call_does_not_leak_its_key(settings, monkeypatch):
    from pipeline import sources

    key = "sekretFREDkey1234"

    def boom(url, params=None, **kw):
        req = httpx.Request("GET", url, params=params)
        raise httpx.HTTPStatusError("Client error '400 Bad Request' for url "
                                    f"'{req.url}'", request=req,
                                    response=httpx.Response(400, request=req))

    monkeypatch.setattr(httpx, "get", boom)
    got = sources.fred_series("UNRATE", _live(settings, fred_api_key=key))
    assert got["status"] != "ok"
    assert key[:3] not in got["reason"]
    assert "400" in got["reason"] and "***" in got["reason"]


def test_a_failed_exhibit_read_is_not_cached(settings, monkeypatch):
    from pipeline import sources

    filing = sources.Filing(ticker="EXMPL", form="8-K", filed="2026-10-16",
                            accession="0001", url="https://sec.example/a/b.htm")
    monkeypatch.setattr(sources, "_filings_of", lambda *a, **k: [filing])
    answers = iter([sources._EXHIBIT_UNREAD,
                    {"url": "u", "text": "Revenue was up."}])
    monkeypatch.setattr(sources, "_find_exhibit", lambda *a: next(answers))
    live = _live(settings)
    assert sources.latest_8k("EXMPL", live)["exhibit_text"] == ""
    assert sources.latest_8k("EXMPL", live)["exhibit_text"] == "Revenue was up."


def test_an_update_candidate_gets_an_update_button():
    from bot.keyboards import candidates_keyboard
    from pipeline.screener import _candidate_lanes

    lanes = _candidate_lanes({"trending": [], "value": [], "updates": ["BBB"]})
    assert lanes == [("BBB", "update")]
    button = candidates_keyboard(lanes).inline_keyboard[0][0]
    assert button.text == "/update BBB"
    assert button.callback_data == "n|u|BBB"


def test_price_and_market_cap_are_one_move():
    from pipeline.standing import Move, _status_for

    moves = [Move("price", 100, 125), Move("market_cap", 1000, 1250),
             Move("shares_out", 50, 53)]
    assert _status_for(moves) == "cracking"


def test_a_plate_cue_counts_as_a_visual_beat():
    from pipeline.repurpose import _WEIGHTS

    assert "asset" not in _WEIGHTS
    assert _WEIGHTS["plate"] > 0.5
