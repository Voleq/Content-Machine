"""Pipeline fixes from the full review of everything outside `bot/`
(31 Oct 2026).

One regression test per finding, named for what it guards. Each of these
failed on the commit before the fix.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest


def _slow(monkeypatch, cls, name):
    """The file is read, then the other thread reads it before this one has
    written: the race a lock is for, made certain."""
    real = getattr(cls, name)

    def slow(self, *a, **kw):
        data = real(self, *a, **kw)
        time.sleep(0.05)
        return data

    monkeypatch.setattr(cls, name, slow)


def _both(*calls):
    threads = [threading.Thread(target=c) for c in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# --------------------------------------------------------------------------
# Two threads writing one state file
# --------------------------------------------------------------------------

def test_two_uploads_recorded_at_once_keep_both_rows(settings, monkeypatch):
    """An upload finishing while the weekly retention pull writes, or two
    uploads at once: `published.json` is read, changed and saved, and the
    second save threw the first one's row away."""
    from pipeline.youtube import VideoLog, VideoRecord

    _slow(monkeypatch, VideoLog, "_all")
    vlog = VideoLog(settings)
    _both(*(lambda v=v: vlog.record(VideoRecord(ticker="EXMPL", video_id=v,
                                                title=v, privacy="private"))
            for v in ("vid-a", "vid-b")))
    assert {v.video_id for v in VideoLog(settings).all()} == {"vid-a", "vid-b"}


@pytest.mark.parametrize("store", ["ideas", "batch", "confessions", "theses"])
def test_two_writers_of_a_standing_file_keep_both(settings, monkeypatch, store):
    """The screen feeding the idea queue while `/ideas` drops one, the
    overnight window marking a job while `/jobs batch` adds one, the alert
    poll re-reading a thesis while a delivery pins another: each store is
    read whole and written whole, and the second write lost the first."""
    from pipeline import standing

    def thesis(ticker):
        return lambda: standing.ThesisBook(settings).record(
            ticker, f"{ticker} thesis", {"revenue": 1.0})

    cls, calls, read = {
        "ideas": (standing.IdeaQueue,
                  [lambda t=t: standing.IdeaQueue(settings).add(t, "moved")
                   for t in ("AAA", "BBB")],
                  lambda: {i.ticker for i in standing.IdeaQueue(settings).ranked()}),
        "batch": (standing.BatchQueue,
                  [lambda t=t: standing.BatchQueue(settings).add(t, "short")
                   for t in ("AAA", "BBB")],
                  lambda: {b.ticker for b in standing.BatchQueue(settings).pending()}),
        "confessions": (standing.ConfessionLedger,
                        [lambda t=t: standing.ConfessionLedger(settings).note(t)
                         for t in ("AAA", "BBB")],
                        lambda: {c.ticker for c in
                                 standing.ConfessionLedger(settings).entries()}),
        "theses": (standing.ThesisBook, [thesis("AAA"), thesis("BBB")],
                   lambda: set(standing.ThesisBook(settings).tickers())),
    }[store]
    _slow(monkeypatch, cls, "_all")
    _both(*calls)
    assert read() == {"AAA", "BBB"}


def test_a_thesis_check_does_not_write_back_an_older_thesis(settings, monkeypatch):
    """The alert poll's `check` read the thesis, then wrote the book back
    with it: a delivery that pinned a new thesis for the same name in
    between was overwritten with the old one."""
    from pipeline import standing

    book = standing.ThesisBook(settings)
    book.record("AAA", "old thesis", {"revenue": 1.0})
    real_get = standing.ThesisBook.get
    pinned = threading.Event()

    def slow_get(self, ticker):
        got = real_get(self, ticker)
        pinned.wait(0.3)          # the delivery lands while the check runs
        return got

    monkeypatch.setattr(standing.ThesisBook, "get", slow_get)
    checker = threading.Thread(
        target=lambda: standing.ThesisBook(settings).check("AAA", {"revenue": 1.0}))
    checker.start()
    time.sleep(0.05)

    def pin():
        standing.ThesisBook(settings).record("AAA", "new thesis", {"revenue": 2.0})
        pinned.set()

    pinner = threading.Thread(target=pin)
    pinner.start()
    checker.join()
    pinner.join()
    monkeypatch.setattr(standing.ThesisBook, "get", real_get)
    assert standing.ThesisBook(settings).get("AAA").summary == "new thesis"


def test_two_names_pinned_to_the_watchlist_at_once_are_both_watched(
        settings, monkeypatch):
    from pipeline.alerts import Watchlist

    _slow(monkeypatch, Watchlist, "_pinned")
    _both(lambda: Watchlist(settings).add("AAA"),
          lambda: Watchlist(settings).add("BBB"))
    assert set(Watchlist(settings)._pinned()) == {"AAA", "BBB"}


def test_two_videos_remembered_at_once_keep_both_jokes(settings, monkeypatch):
    """A delivery remembering its jokes while the page saves the edited
    list: `used_jokes.json` is read whole and written whole."""
    from pipeline.channel_memory import JokeBook, _Book

    _slow(monkeypatch, _Book, "_rows")
    _both(*(lambda k=k: JokeBook(settings).add(
        f"{k}/2026-10-31/short", [f"the {k.lower()} joke about the margin line"],
        ticker=k, workdate="2026-10-31", fmt="short") for k in ("AAA", "BBB")))
    assert {r.ticker for r in JokeBook(settings).all()} == {"AAA", "BBB"}


# --------------------------------------------------------------------------
# State files written in place
# --------------------------------------------------------------------------

def _write_that_dies(monkeypatch, target_name: str) -> dict:
    """`Path.write_text` / `write_bytes` for one file name writes half and
    then fails, as a full disk or a kill does. Set `["on"] = False` on what
    comes back and they write normally again."""
    real_text, real_bytes = Path.write_text, Path.write_bytes
    state = {"on": True}

    def text(self, data, *a, **kw):
        if state["on"] and target_name in self.name:
            real_text(self, data[: len(data) // 2], *a, **kw)
            raise OSError(28, "No space left on device")
        return real_text(self, data, *a, **kw)

    def raw(self, data):
        if state["on"] and target_name in self.name:
            real_bytes(self, data[: len(data) // 2])
            raise OSError(28, "No space left on device")
        return real_bytes(self, data)

    monkeypatch.setattr(Path, "write_text", text)
    monkeypatch.setattr(Path, "write_bytes", raw)
    return state


def test_an_alert_log_write_that_dies_keeps_what_was_said(settings, monkeypatch):
    """The alert log was rewritten in place: a write cut short left half a
    file, which reads as nothing said, and every name alerted again."""
    from pipeline.alerts import Alert, AlertLog

    log_ = AlertLog(settings)
    log_.record(Alert(ticker="AAA", kind="move", headline="down 9%",
                      magnitude=9.0))
    before = log_.path.read_text(encoding="utf-8")
    dying = _write_that_dies(monkeypatch, log_.path.name)
    with pytest.raises(OSError):
        log_.record(Alert(ticker="BBB", kind="move", headline="up 9%",
                          magnitude=9.0))
    dying["on"] = False
    assert log_.path.read_text(encoding="utf-8") == before
    assert "AAA" in AlertLog(settings)._all()


def test_a_filing_download_that_dies_is_not_kept_as_the_filing(settings,
                                                              monkeypatch, tmp_path):
    """The 10-K was written straight to its cache name, and a download cut
    short was served as the filing from then on (`size > 0`)."""
    from pipeline import filings

    live = settings.model_copy(update={"mock_mode": False})
    ref = filings.FilingRef(ticker="EXMPL", cik="0000000001", form="10-K",
                            accession="0000000001-26-000001",
                            primary_doc="x.htm", url="https://www.sec.gov/x.htm",
                            filed="2026-02-01", period="2025-12-31")
    body = b"<html>" + b"x" * 4000 + b"</html>"
    monkeypatch.setattr(filings, "_sec_get", lambda url, s: NS(content=body))
    ws = tmp_path / "ws"
    dying = _write_that_dies(monkeypatch, filings.filing_path(ref, ws).stem)
    with pytest.raises(OSError):
        filings.download_filing(ref, ws, live)
    dying["on"] = False
    got = filings.download_filing(ref, ws, live)
    assert got.read_bytes() == body


def test_a_price_cache_that_cannot_be_written_does_not_stop_the_chart(
        settings, monkeypatch):
    """`get_price_history` never raises, by contract: a chart must never
    abort a render. Its last line wrote the cache unguarded, so a full disk
    raised out of the price gate and the chart."""
    from pipeline import prices

    _write_that_dies(monkeypatch, "EXMPL_")
    series = prices.get_price_history("EXMPL", settings)
    assert len(series.closes) >= 2


def test_a_clip_cut_short_while_normalising_is_not_served_from_the_cache(
        settings, monkeypatch, tmp_path):
    """A clip was normalised straight into its cache name. Killed or failed
    half way (an update stops the bot mid-render), the half file was a cache
    hit for every later render of that clip, and each of them failed on it."""
    from pipeline import broll
    from pipeline.render_common import RenderError

    def dies(args, **kw):
        Path(args[-1]).write_bytes(b"\x00\x00\x00\x18ftypmp42 half a clip")
        raise RenderError("ffmpeg failed (255): killed")

    monkeypatch.setattr(broll, "run_ffmpeg", dies)
    dest = tmp_path / "broll" / "normalized_0.mp4"
    with pytest.raises(RenderError):
        broll.normalize_clip(tmp_path / "raw.mp4", dest, settings)
    assert not dest.exists()
    assert not list(dest.parent.glob("*.part*")), "the part file is cleaned up"


def test_a_meme_cut_short_while_saving_is_not_served_from_the_cache(tmp_path,
                                                                   monkeypatch):
    from PIL import Image

    from pipeline.memes import normalize_meme

    src = tmp_path / "raw.png"
    Image.new("RGB", (40, 30), (200, 10, 10)).save(src)
    real_save = Image.Image.save

    def dies(self, fp, *a, **kw):
        Path(fp).write_bytes(b"\x89PNG half")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", dies)
    dest = tmp_path / "memes" / "norm.png"
    with pytest.raises(OSError):
        normalize_meme(src, dest)
    monkeypatch.setattr(Image.Image, "save", real_save)
    assert not dest.exists()


# --------------------------------------------------------------------------
# Reading the sources
# --------------------------------------------------------------------------

def test_a_filing_excerpt_has_its_entities_decoded():
    """Five entities were decoded by hand; `&#8220;`, `&mdash;`, `&#x25;`
    and the rest reached the prompt and the release card as written."""
    from pipeline.sources import _strip_html

    got = _strip_html("<p>Q3 &#8220;record&#8221; &mdash; up 5&#x25; "
                      "&amp; &nbsp;more</p>")
    assert got == "Q3 “record” — up 5% & more"


def test_a_fraction_written_as_a_percentage_reads_as_the_fraction():
    """A yield or an ownership share is a fraction (0.015), and "1.5%" in a
    CSV or a text cell was read as 1.5 — a 150% dividend yield on the
    prompt. Only the fraction fields: a margin on the History sheet is
    held as a percent already."""
    from pipeline.company_data import _coerce

    assert _coerce("dividend_yield", "1.5%") == pytest.approx(0.015)
    assert _coerce("insider_own", " 12 % ") == pytest.approx(0.12)
    assert _coerce("dividend_yield", 0.015) == pytest.approx(0.015)
    assert _coerce("dividend_yield", "0.015") == pytest.approx(0.015)
    assert _coerce("price", "12.50") == pytest.approx(12.5)


def test_a_headline_names_the_company_by_word_not_by_letters():
    """The ticker was matched as a word and the name as letters, so
    "Metals rally" was a headline about Meta and "pineapple" about Apple."""
    from pipeline.models import CompanyData

    meta = CompanyData(values={"ticker": "META",
                               "company_name": "Meta Platforms, Inc."})
    assert meta.names_company("Meta beats on ads")
    assert meta.names_company("Meta's AI spend doubles")
    assert not meta.names_company("Metals rally as the dollar slips")
    apple = CompanyData(values={"ticker": "AAPL", "company_name": "Apple Inc."})
    assert not apple.names_company("Pineapple prices hit a record")


# --------------------------------------------------------------------------
# The voice
# --------------------------------------------------------------------------

def test_a_rate_limit_that_says_when_as_a_date_is_waited_out(
        settings, alignment_sample, tmp_path, monkeypatch):
    """`Retry-After` may be a date as well as seconds. A date raised a
    ValueError out of the voice and failed the job on a 429 that is only
    ever a request to wait."""
    import pipeline.tts as tts_mod
    from pipeline.cost import SpendLedger
    from pipeline.tts import TTSEngine, chunk_text
    from tests.test_tts import _live, _multi_chunk_text, _tiny_mp3_b64

    waited: list = []
    monkeypatch.setattr(tts_mod.time, "sleep", waited.append)
    audio_b64 = _tiny_mp3_b64(tmp_path)
    live = _live(settings)
    text = _multi_chunk_text()
    n_chunks = len(chunk_text(text, live.tts_chunk_chars))
    calls: list = []
    when = (datetime.now(timezone.utc) + timedelta(seconds=10)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT")

    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": when},
                                  text='{"detail": "slow down"}')
        return httpx.Response(200, json={"audio_base64": audio_b64,
                                         "alignment": alignment_sample["alignment"]})

    engine = TTSEngine(live, ledger=SpendLedger(live),
                       client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = engine.synthesize(text, "long")
    assert result.audio_path.exists()
    assert len(calls) == n_chunks + 1
    assert waited and 0 < waited[0] <= 30


def test_retry_after_reads_seconds_dates_and_nonsense():
    from pipeline.tts import _retry_after_s

    assert _retry_after_s("12", 2.0) == 12.0
    assert _retry_after_s("-5", 2.0) == 2.0
    assert _retry_after_s("soon", 2.0) == 2.0
    assert _retry_after_s(None, 4.0) == 4.0
    past = "Wed, 21 Oct 2015 07:28:00 GMT"
    assert _retry_after_s(past, 2.0) == 2.0


# --------------------------------------------------------------------------
# Scheduled pushes reach every operator
# --------------------------------------------------------------------------

class _App:
    """Just enough of a PTB Application for the schedulers to register."""

    def __init__(self):
        self.jobs: dict = {}
        self.job_queue = NS(
            run_daily=lambda fn, **kw: self.jobs.__setitem__(kw["name"], fn),
            run_once=lambda fn, **kw: self.jobs.__setitem__(kw["name"], fn),
            run_repeating=lambda fn, **kw: self.jobs.__setitem__(kw["name"], fn))


class _Bot:
    def __init__(self, failing):
        self.failing, self.sent = failing, []

    async def send_message(self, chat_id, text, **kw):
        if chat_id == self.failing:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


def _core(settings):
    from bot.feed import Feed
    from bot.handlers import BotCore

    core = BotCore(settings.model_copy(update={"operator_chat_ids": [11, 22]}))
    core.feed = Feed()
    return core


def test_the_morning_screen_reaches_every_operator_and_the_page(settings):
    """One chat that had blocked the bot stopped the digest at it: the next
    chat never heard, the day was never marked sent (so every restart sent
    it again) and the page's Activity never had it."""
    from pipeline.screener import last_digest_date, schedule_digest

    core, app, bot = _core(settings), _App(), _Bot(failing=11)
    schedule_digest(app, core)
    asyncio.run(app.jobs["screen_digest"](NS(bot=bot)))
    assert [c for c, _t, _k in bot.sent] == [22]
    assert bot.sent[0][1].startswith("🌅 Morning screen")
    assert last_digest_date(core.settings) is not None
    assert any("Morning screen" in e.text for e in core.feed.since(0))


def test_an_intraday_alert_reaches_every_operator_and_the_page(settings,
                                                              monkeypatch):
    from pipeline import alerts as alerts_mod
    from pipeline.alerts import Alert
    from pipeline.screener import schedule_alerts

    core = _core(settings)
    core.settings.alerts_enabled = True
    app, bot = _App(), _Bot(failing=11)
    monkeypatch.setattr(alerts_mod, "in_quiet_hours", lambda s, now=None: False)
    monkeypatch.setattr(alerts_mod, "fetch_quotes", lambda s, t: [])
    monkeypatch.setattr(alerts_mod, "fetch_filings", lambda s, t: [])
    monkeypatch.setattr(alerts_mod, "poll_once", lambda s, **kw: [
        Alert(ticker="AAA", kind="move", headline="down 9%", magnitude=9.0)])
    schedule_alerts(app, core)
    asyncio.run(app.jobs["intraday_alerts"](NS(bot=bot)))
    assert [c for c, _t, _k in bot.sent] == [22]
    assert any("AAA" in e.text for e in core.feed.since(0))


# --------------------------------------------------------------------------
# The gates, and what they cost
# --------------------------------------------------------------------------

class _Counting(dict):
    def __init__(self, *a):
        super().__init__(*a)
        self.calls = 0

    def values(self):
        self.calls += 1
        return super().values()


def test_the_kit_doctor_walks_the_library_once_not_once_per_plate(settings,
                                                                monkeypatch):
    """`reachable_plates` looked for a slot naming each plate by walking
    every slot of every plate, for every plate: ten million steps and most
    of the twelve seconds `/kit doctor` took."""
    from pipeline.gates import reachable_plates
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    counting = _Counting(reg.assets)
    monkeypatch.setattr(reg, "assets", counting)
    reachable_plates(reg)
    assert counting.calls < 50, counting.calls


def test_the_kit_doctor_reads_the_renderer_wherever_it_is_started(
        settings, monkeypatch, tmp_path):
    """The renderer's own source was read from `Path("pipeline")`, relative
    to the working directory: started anywhere but the repo, every plate the
    code reaches by name read as reachable by nothing."""
    from pipeline.gates import reachable_plates
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    here = reachable_plates(reg)["code"]
    monkeypatch.chdir(tmp_path)
    assert reachable_plates(reg)["code"] == here


def test_the_used_jokes_check_reads_the_book_once(settings, monkeypatch):
    """Every sentence of the script re-read `used_jokes.json` and re-split
    every joke in it: four seconds at a thousand jokes, growing with every
    video, on every check of every script."""
    from pipeline.channel_memory import JokeBook, _Book, joke_reuse_lint

    JokeBook(settings).add("AAA/2026-10-01/long",
                           ["the dragon guarding a spreadsheet of margins"],
                           ticker="AAA", workdate="2026-10-01", fmt="long")
    reads = {"n": 0}
    real = _Book._rows

    def counted(self):
        reads["n"] += 1
        return real(self)

    monkeypatch.setattr(_Book, "_rows", counted)
    narration = "\n".join(f"Sentence {i} about revenue and the quarter." for i in
                          range(40)) + "\nA dragon guarding a spreadsheet of margins."
    found = joke_reuse_lint(narration, settings)
    assert len(found) == 1
    assert reads["n"] <= 2, reads["n"]


# --------------------------------------------------------------------------
# Thesis tracking
# --------------------------------------------------------------------------

def _workbook_data(settings, tmp_path):
    import shutil

    from pipeline.company_data import load_company_data

    ws = tmp_path / "EXMPL" / "2026-10-31"
    ws.mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" / "company_data"
                / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    return load_company_data(ws)


def test_a_thesis_pins_the_revenue_it_was_about(settings, tmp_path):
    """The book tracked `revenue_ltm`, which no sheet carries: revenue — the
    number most videos are about — was never pinned, and a 30% fall in it
    could never move a thesis. The History sheet's last column is LTM."""
    from pipeline.standing import ThesisBook

    data = _workbook_data(settings, tmp_path)
    t = ThesisBook(settings).record("EXMPL", "the slowdown", data)
    assert t.numbers["revenue"] == data.history["revenue"][-1]


def test_a_margin_is_judged_in_points_not_as_a_share_of_itself(settings):
    """Half a point on a 10% margin was a 5% move, material, and pushed as
    "gross_margin ↑5%"; a margin from -2% to 1% read "↑150%". A rate moves in
    points everywhere else in the code (`quarter_moves`, `short_data.change`)."""
    from pipeline.standing import Move, _status_for

    assert not Move("gross_margin", 10.0, 10.5).material
    four = Move("gross_margin", 62.0, 58.0)
    assert four.material
    assert four.render() == "gross_margin ↓4.0 pts (62 → 58)"
    turn = Move("operating_margin", -2.0, 1.0)
    assert turn.render() == "operating_margin ↑3.0 pts (-2 → 1)"
    assert _status_for([four]) == "cracking"
    # A price is still a percentage of itself.
    assert Move("price", 100.0, 125.0).render() == "price ↑25% (100 → 125)"


def test_the_scoreboard_says_a_margin_moved_in_points(settings):
    from pipeline.scoreboard import Row

    row = Row(ticker="EXMPL", status="cracking", summary="margins",
              workdate="2026-10-01",
              moves=[{"field": "gross_margin", "before": 62.0, "after": 58.0,
                      "change": -0.0645}])
    assert "gross_margin moved ↓4.0 pts" in row.line()


def test_a_correction_keeps_the_retention_pulled_while_it_posted(settings):
    """`pin_correction` read the row, posted to YouTube (seconds), then wrote
    the whole row back: retention the weekly pass pulled meanwhile was
    overwritten with the row as it was before."""
    from pipeline.youtube import VideoLog, VideoRecord, pin_correction

    live = settings.model_copy(update={"mock_mode": False})
    VideoLog(live).record(VideoRecord(ticker="EXMPL", video_id="vid-1",
                                      title="t", privacy="public",
                                      uploaded_at="2026-10-01T10:00:00+00:00"))

    class Client:
        def comment(self, video_id, body):
            # the weekly pull lands while the comment is going up
            VideoLog(live).update_retention(video_id, {"rows": [[0.5, 0.9]]})

        def append_description(self, video_id, text):
            pass

    pin_correction("EXMPL", "revenue was $496M, not $469M", live,
                   video_id="vid-1", client=Client())
    row = VideoLog(live).get("vid-1")
    assert row.retention == {"rows": [[0.5, 0.9]]}
    assert [c["text"] for c in row.corrections] == ["revenue was $496M, not $469M"]


def test_a_clip_cut_short_while_repurposing_is_not_left_as_a_clip(settings,
                                                                 tmp_path,
                                                                 monkeypatch):
    """`/repurpose` encoded each clip straight to `short_repurposed_N.mp4`.
    Stopped half way (an update stops the bot mid-job, a kill), the half file
    was named like a finished clip, and the video card counted it as one."""
    from pipeline import repurpose
    from pipeline.render_common import RenderError

    def dies(args, **kw):
        Path(args[-1]).write_bytes(b"\x00\x00\x00\x18ftypisom half a clip")
        raise RenderError("ffmpeg failed (255): killed")

    monkeypatch.setattr(repurpose, "run_ffmpeg", dies)
    out = tmp_path / "short_repurposed_1.mp4"
    with pytest.raises(RenderError):
        repurpose._cut_window(tmp_path / "long_final.mp4", 10.0, 40.0, out,
                              settings)
    assert not out.exists()
    assert not list(tmp_path.glob("short_repurposed_*")), "nothing left behind"


# --------------------------------------------------------------------------
# Figures, as they are said
# --------------------------------------------------------------------------

def test_a_decimal_is_suggested_as_a_person_says_it():
    """A trailing zero is typed, never said: "12.30%" was suggested as
    "twelve point three zero percent" and "$5.00bn" as "five point zero zero
    billion dollars"."""
    from pipeline.spoken import eye_written_figures

    said = dict(eye_written_figures(
        "growth of 12.30%, a 10.0% yield, a $5.00bn buyback, 2.50x sales, "
        "$1,234.56 of cash and pi at 3.14159"))
    assert said["12.30%"] == "twelve point three percent"
    assert said["10.0%"] == "ten percent"
    assert said["$5.00bn"] == "five billion dollars"
    assert said["2.50x"] == "two point five times"
    assert said["$1,234.56"] == ("one thousand two hundred and thirty-four "
                                 "dollars and fifty-six cents")
    assert said["3.14159"] == "three point one four one five nine"


def _words(text: str, start: float = 10.0):
    return [NS(word=w, start=start + i * 0.3, end=start + i * 0.3 + 0.25)
            for i, w in enumerate(text.split())]


@pytest.mark.parametrize("figure, said, lands_on", [
    ("$1.20", "earnings came in at one point two dollars a share", 4),
    ("$1.20", "earnings came in at one dollar and twenty cents a share", 4),
    ("12.0x", "it trades at twelve times earnings", 3),
    ("$5.00bn", "a five billion dollar buyback", 1),
    ("12.30%", "growth of twelve point three percent", 2),
    ("$3.1bn", "revenue of three point one billion dollars", 2),
    ("−18.4%", "down eighteen point four percent on the year", 1),
])
def test_a_figure_on_a_card_is_heard_however_it_was_written(figure, said,
                                                           lands_on):
    """A card's figure counts up as it is said, so `moves` listens for it.
    It listened for "one point two zero" for "$1.20": a per-share figure
    (always two places on a card) and a multiple ("12.0x") were never heard,
    and counted up when the shot opened instead."""
    from pipeline.moves import _heard, _said_forms

    words = _words(said)
    at = _heard(words, _said_forms(figure), 0.0, 99.0)
    assert at == pytest.approx(words[lands_on].start), (figure,
                                                        _said_forms(figure))


# --------------------------------------------------------------------------
# Earnings alerts
# --------------------------------------------------------------------------

def test_an_after_the_close_print_is_a_reaction_the_same_evening(settings):
    """A `bmo` print flipped to "the numbers are out" at the open; an `amc`
    one only on the next calendar day, so with the 9-17 window the alert
    the docstring calls "the one that has to go out fast" went out at nine
    the next morning, after the after-hours and pre-market move."""
    from zoneinfo import ZoneInfo

    from pipeline.alerts import REPORTED, EarningsCalendar

    ny = ZoneInfo(settings.screen_timezone)
    cal = EarningsCalendar(settings)
    cal.set("EXMPL", "2026-07-29", "amc")
    noon = cal.due_alerts(datetime(2026, 7, 29, 12, 0, tzinfo=ny))
    assert [a.headline for a in noon] == ["reports after the close"]
    evening = cal.due_alerts(datetime(2026, 7, 29, 16, 45, tzinfo=ny))
    assert [a.headline for a in evening] == [REPORTED]
    assert cal.due_alerts(datetime(2026, 7, 30, 9, 15, tzinfo=ny)) == [], \
        "said once"


# --------------------------------------------------------------------------
# What kind of day
# --------------------------------------------------------------------------

def _meta():
    from pipeline.models import CompanyData

    return CompanyData(values={"ticker": "META",
                               "company_name": "Meta Platforms, Inc."})


def test_another_company_s_print_does_not_make_this_an_earnings_day():
    """Every headline dated in the window counted, naming the company or
    not — and the News sheet carries market stories that only tag it. So
    "Nvidia Q3 earnings beat" in META's feed cut META's short as an earnings
    reaction, and any headline at all made it a company-news day."""
    from datetime import date

    from pipeline.move_kind import EARNINGS, MOVE, NEWS, classify

    today = date(2026, 10, 30)
    other = {"date": "2026-10-30", "source": "Reuters",
             "headline": "Nvidia Q3 earnings beat estimates as data centres boom"}
    day = classify("META", today, news=[other], names=_meta().names_company)
    assert day.kind == MOVE, day.why
    named = {"date": "2026-10-29", "source": "Reuters",
             "headline": "Meta shares slide as ad growth slows"}
    day = classify("META", today, news=[other, named],
                   names=_meta().names_company)
    assert day.kind == NEWS and "Meta shares slide" in day.why
    # The company's own feed is its own, whatever the title says.
    own = {"date": "2026-10-29", "source": "company IR",
           "headline": "Third Quarter 2026 Results"}
    day = classify("META", today, news=[other, own],
                   names=_meta().names_company)
    assert day.kind == EARNINGS


def test_the_writer_is_told_which_headlines_do_not_name_the_company(settings):
    from datetime import date

    from bot.prompts import why_it_moved_block
    from pipeline.move_kind import classify

    day = classify("META", date(2026, 10, 30), names=_meta().names_company,
                   news=[{"date": "2026-10-30", "source": "Reuters",
                          "headline": "Nvidia Q3 earnings beat estimates"},
                         {"date": "2026-10-29", "source": "Reuters",
                          "headline": "Meta shares slide as ad growth slows"}])
    ws = settings.workspace_dir / "META" / "2026-10-30"
    ws.mkdir(parents=True)
    ctx = NS(move_kind=day, ticker="META", workspace=ws, settings=settings)
    block = why_it_moved_block(ctx)
    named_at = block.index("Meta shares slide")
    other_at = block.index("Nvidia Q3 earnings")
    caution = block.index("not naming the company")
    assert named_at < caution < other_at


def test_before_the_open_yesterday_s_volume_is_not_news(settings):
    """Before the open a quote's volume is the last session's, whole — the
    reason its price change is already left alone. The volume note was not,
    so every morning a name that traded heavily yesterday was "3.0× normal
    volume — something is going on" again."""
    from pipeline.alerts import evaluate

    q = {"symbol": "AAA", "regularMarketPrice": 10.0,
         "regularMarketChangePercent": 1.0, "regularMarketVolume": 9_000_000,
         "averageDailyVolume3Month": 2_000_000}
    assert evaluate({**q, "sessionStarted": False}, settings) == []
    assert [a.kind for a in evaluate({**q, "sessionStarted": True},
                                     settings)] == ["volume"]
