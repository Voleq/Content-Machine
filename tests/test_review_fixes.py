"""Regression tests for the fixes from the project-wide review (2026-10-05).

Each test names the finding it pins. They are written against the behaviour
the operator sees — what renders, what is refused, what is recorded — rather
than against the helper that fixed it, wherever that is cheap enough to run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from bot.handlers import BotCore, telegram_send_kind
from config import Settings
from pipeline.workspace import Workspace

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CHAT = 4242


@pytest.fixture()
def core(settings):
    small = settings.model_copy(update={
        "short_width": 540, "short_height": 960,
        "long_width": 640, "long_height": 360,
    })
    return BotCore(small)


# --------------------------------------------------------------------- H1


class _Took(Exception):
    def __init__(self, key: str, choice: int):
        super().__init__(key)
        self.key, self.choice = key, choice


def test_a_swapped_clip_is_the_clip_the_render_draws(settings, monkeypatch):
    """H1: the swap menu writes `CLIP:k`; the renderer looked overrides up by
    payload and drew take 0, so the approved report and the video differed."""
    from pipeline.broll import ContentManager
    from pipeline.parser_long import parse_long_script
    from pipeline.render_long import render_long
    from pipeline.tts import TTSEngine

    s = settings.model_copy(update={"long_min_chars": 0,
                                    "long_width": 320, "long_height": 180})
    raw = ("EXMPL is down sixty percent and nobody cares. [CLIP: tumbleweed] "
           "Which is when I start reading the filings, slowly, at night.\n\n"
           "=== CHAPTERS ===\n00:00 cold-open | nobody cares anymore\n")
    script, _ = parse_long_script(raw, "EXMPL", s)
    ws = s.workspace_dir / "EXMPL" / "2026-07-01"
    ws.mkdir(parents=True)
    tts = TTSEngine(s).synthesize(script.narration, "long")

    def took(self, key, choice=0, **_kw):
        raise _Took(key, choice)

    monkeypatch.setattr(ContentManager, "resolve_clip", took)
    with pytest.raises(_Took) as got:
        render_long(script, tts, ws, s, content=ContentManager(s),
                    broll_overrides={"CLIP:0": 3})
    assert got.value.key == "tumbleweed" and got.value.choice == 3


def test_a_meme_gets_no_swap_button_and_keeps_its_index(core, monkeypatch):
    """A meme has one take; its button counted "take 2/6" and changed
    nothing. The index space every stored override uses is unchanged."""
    from bot.keyboards import swap_keyboard

    kb = swap_keyboard("EXMPL", "2026-07-01", [(0, "1. tumbleweed"),
                                                (2, "3. warehouse")])
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "s|EXMPL|2026-07-01|0" in data and "s|EXMPL|2026-07-01|2" in data
    assert not any(d.endswith("|1") for d in data)


# --------------------------------------------------------------------- H2


def test_a_push_the_cloud_api_would_refuse_is_refused_here(settings, tmp_path):
    big = tmp_path / "proof.mp4"
    with open(big, "wb") as fh:
        fh.truncate(51_000_000)
    with pytest.raises(ValueError, match="50 MB"):
        telegram_send_kind(big, settings)
    local = settings.model_copy(update={"telegram_api_base_url": "http://x"})
    assert telegram_send_kind(big, local) == "video"


def test_a_tall_contact_sheet_goes_as_a_document(settings, tmp_path):
    tall = tmp_path / "storyboard.png"
    Image.new("RGB", (400, 9800), (0, 0, 0)).save(tall)
    assert telegram_send_kind(tall, settings) == "document"
    small = tmp_path / "thumb.png"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(small)
    assert telegram_send_kind(small, settings) == "photo"


# --------------------------------------------------------------------- H3


def test_a_failed_screenshot_does_not_shift_the_quotes(settings, tmp_path,
                                                       monkeypatch):
    """H3: shots were paired with quotes by position, and the browser skips
    a shot it cannot take — every later image then carried the wrong quote."""
    import pipeline.company_data as company_data
    import pipeline.filings as filings

    live = settings.model_copy(update={"filings_enabled": True})
    ws = tmp_path / "ws"
    ws.mkdir()
    html = ws / "filing.htm"
    html.write_text("<p>a</p>", encoding="utf-8")
    quotes = [filings.FlaggedQuote(q, f"S{i}", f"why {i}")
              for i, q in enumerate(("first quote", "second quote", "third quote"))]
    shots = []
    for name in ("b", "c"):
        p = tmp_path / f"raw_{name}.png"
        Image.new("RGB", (10, 10)).save(p)
        shots.append(p)
    monkeypatch.setattr(filings, "resolve_filing", lambda *a, **k: filings.FilingRef(
        ticker="EXMPL", cik="1", form="10-K", accession="a", primary_doc="d",
        url="u"))
    monkeypatch.setattr(filings, "download_filing", lambda *a, **k: html)
    monkeypatch.setattr(filings, "segment_filing", lambda h: [])
    monkeypatch.setattr(filings, "flag_quotes", lambda *a, **k: quotes)
    monkeypatch.setattr(filings, "locate_quote", lambda h, q: {"quote": q})
    monkeypatch.setattr(filings, "screenshot_quotes",
                        lambda *a, **k: [None, shots[0], shots[1]])
    monkeypatch.setattr(company_data, "prepare_screenshot",
                        lambda src, dest, s: shutil.copy(src, dest))

    got = filings.auto_filings("EXMPL", "angle", ws, live)
    assert [(s.name, s.quote) for s in got] == [
        ("filing_01.png", "second quote"), ("filing_02.png", "third quote")]


# --------------------------------------------------------------------- H4


def test_a_macro_short_is_approvable_under_the_production_default(settings):
    """H4: no workbook → no as-of date → the freshness gate BLOCKED every
    macro short with `DATA_STALE_BLOCKS=true`, which the suite turns off."""
    prod = settings.model_copy(update={"data_stale_blocks": True,
                                       "short_width": 540, "short_height": 960})
    core = BotCore(prod)
    h = json.loads((FIXTURES / "headlines" / "headlines.json")
                   .read_text(encoding="utf-8"))["macro"]
    core.headline_command(CHAT, [h["symbol"], *h["headline"].split()])
    macro = (FIXTURES / "scripts" / "headline_macro.json").read_text(encoding="utf-8")
    reply = core.intake_script(CHAT, macro)
    assert "ready to render" in reply.text, reply.text
    assert "no as-of date" not in reply.text


# --------------------------------------------------------------------- H6


def test_hosted_llm_spend_is_metered_and_capped(settings, monkeypatch):
    from pipeline import llm
    from pipeline.cost import SpendLedger

    live = settings.model_copy(update={
        "mock_mode": False, "openai_api_key": "k", "llm_provider_order": "openai",
        "llm_monthly_cap_usd": 0.0005})
    monkeypatch.setattr(llm, "_post", lambda *a, **k: {
        "choices": [{"message": {"content": "an answer"}}],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 1000}})
    first = llm.chat_result("q", live, purpose="skeptic")
    assert first.text == "an answer"
    spent = SpendLedger(live).llm_usd_this_month()
    assert spent == pytest.approx(2 * 0.00015 + 1 * 0.0006)
    second = llm.chat_result("q", live, purpose="skeptic")
    assert not second and second.reason == llm.CAPPED


# --------------------------------------------------------------------- M1


def test_the_thread_cap_reaches_the_encoder(tmp_path):
    """M1: `-threads` in front of the input capped the DECODER; x264 ran at
    its own count. The encoder's SEI says what it used."""
    from pipeline.render_common import _POLITENESS, run_ffmpeg

    saved = dict(_POLITENESS)
    _POLITENESS.update({"threads": 1, "below_normal": False})
    try:
        out = tmp_path / "t.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc=s=320x240:d=0.5",
                    "-c:v", "libx264", "-preset", "veryfast", str(out)])
    finally:
        _POLITENESS.clear()
        _POLITENESS.update(saved)
    assert b"threads=1 " in out.read_bytes()


# --------------------------------------------------------------------- M3


def test_render_finds_the_folder_with_the_script_not_just_the_newest(settings):
    old = Workspace(settings, "EXMPL", "2026-09-01").create()
    old.set_lane("long")
    (old.path / "script_long.json").write_text("{}", encoding="utf-8")
    new = Workspace(settings, "EXMPL", "2026-09-02").create()
    new.set_lane("short")
    (settings.workspace_dir / "EXMPL" / "scratch").mkdir()

    def has_long(w):
        return (w.path / "script_long.json").exists()

    assert Workspace.latest_for(settings, "EXMPL").workdate == "2026-09-02"
    assert Workspace.resolve(settings, "EXMPL", has_long).workdate == "2026-09-01"
    assert Workspace.resolve(settings, "EXMPL@2026-09-01").workdate == "2026-09-01"
    assert Workspace.resolve(settings, "EXMPL@2026-01-01") is None


# --------------------------------------------------------------------- M4


def test_the_free_voice_never_splits_a_figure():
    from pipeline.local_tts import split_sentences

    text = ("Revenue went from 1,234 million to 2,345 million over six years "
            "while the share count went up and up and up and nobody at the "
            "company seemed to mind at all, which is a thing. It grew 4.7 "
            "percent.")
    parts = split_sentences(text)
    assert all(p in text for p in parts), "every piece is a slice of the text"
    assert not any("1, 234" in p for p in parts)
    assert "It grew 4.7 percent." in parts


# --------------------------------------------------------------------- M7


def test_a_segment_reads_the_clips_its_ffconcat_names(tmp_path):
    from pipeline.segments import SegmentSpec

    clip = tmp_path / "screenin_0_room.mov"
    clip.write_bytes(b"one")
    listing = tmp_path / "screenin_0_room.ffconcat"
    listing.write_text(f"ffconcat version 1.0\nfile '{clip}'\n", encoding="utf-8")
    spec = SegmentSpec(index=0, kind="host", duration=1.0, width=320,
                       height=180, fps=30,
                       inputs=(("-f", "concat", "-safe", "0", "-i", str(listing)),),
                       filter_chain="[0:v]null[out]")
    before = spec.stamps()
    clip.write_bytes(b"two!")          # same path, new draw-in
    assert spec.stamps() != before


# --------------------------------------------------------------------- M8


def test_a_guessed_chapter_start_lands_on_its_paragraph():
    from pipeline.models import WordTimestamp
    from pipeline.timeline import measured_chapter_times

    narration = ("one two three four five six. seven eight nine ten.\n\n"
                 "eleven twelve thirteen fourteen fifteen sixteen.")
    words, t, c = [], 0.0, 0
    for w in narration.split():
        i = narration.index(w, c)
        words.append(WordTimestamp(word=w, start=t, end=t + 0.5,
                                   char_start=i, char_end=i + len(w)))
        t += 0.5
        c = i + len(w)
    para = next(w.start for w in words if w.word == "eleven")
    got = measured_chapter_times([0.0, 3.0], narration, words, t)
    assert got == [0.0, para]


# --------------------------------------------------------------------- M10


def test_an_edit_keeps_the_line_breaks_it_was_typed_with(core, settings,
                                                         long_valid_text):
    core.start_lane(CHAT, "long", "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    ws.clear_awaiting_angle()
    core.handle_upload(CHAT, "script.txt", long_valid_text.encode("utf-8"))
    before = ws.raw_script("long")
    n = len(before.splitlines())
    core.edit_script(CHAT, [], raw_args="1 First line here.\nSecond line here.")
    after = ws.raw_script("long")
    assert after.splitlines()[:2] == ["First line here.", "Second line here."]
    assert len(after.splitlines()) == n + 1


# --------------------------------------------------------------------- M11


def test_a_batch_render_that_fails_is_still_queued(core, settings):
    from pipeline.jobs import JobStore
    from pipeline.models import JobKind, JobRecord, JobStatus
    from pipeline.standing import BatchQueue

    class _Q:
        store = JobStore(settings)

    core.queue = _Q()
    b = BatchQueue(settings)
    b.add("EXMPL", "long")
    job = JobRecord(id="j1", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                    workdate="2026-07-01", status=JobStatus.FAILED,
                    error="ffmpeg died")
    _Q.store.save(job)
    b.mark_submitted("EXMPL", "long", "j1")
    core.batch_plan()
    item = b.pending()[0]
    assert item.job_id == "" and "ffmpeg died" in item.error


# --------------------------------------------------------------------- M12


def test_a_final_on_mocked_prices_is_blocked_when_live(settings, short_valid_json):
    from pipeline.gates import check_prices
    from pipeline.parser_short import parse_short_script

    live = settings.model_copy(update={"mock_mode": False, "mock_prices": True})
    script, _ = parse_short_script(short_valid_json, live)
    found = check_prices(script, live, final=True)
    assert found and found[0].severity == "block"
    assert "MOCK_PRICES" in found[0].message


# --------------------------------------------------------------- low items


def test_the_tail_of_a_split_paste_is_refused_too(core, settings):
    core.start_lane(CHAT, "long", "EXMPL")
    Workspace.latest_for(settings, "EXMPL").clear_awaiting_angle()
    core.intake_script(CHAT, "A" * 4096)
    reply = core.intake_script(CHAT, "the [CLIP: tumbleweed] end of it")
    assert ".txt" in reply.text
    assert Workspace.latest_for(settings, "EXMPL").load_long() is None


def test_a_checkpoint_never_writes_over_a_cancel(settings):
    from pipeline.jobs import JobStore
    from pipeline.models import JobKind, JobRecord, JobStatus

    store = JobStore(settings)
    store.save(JobRecord(id="j", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                         workdate="2026-07-01", status=JobStatus.RUNNING))

    def cancel(j):
        j.status = JobStatus.CANCELLED

    store.update("j", cancel)

    def note(j):
        if j.status is JobStatus.CANCELLED:
            raise RuntimeError("cancelled")
        j.detail = "render 5/10"

    with pytest.raises(RuntimeError):
        store.update("j", note)
    assert store.load("j").status is JobStatus.CANCELLED


def test_odd_workspace_paths_survive_the_subtitle_filter(tmp_path):
    from config import detect_ffmpeg
    from pipeline.render_common import filter_path

    d = tmp_path / "it's:here[1],x"
    d.mkdir()
    ass = d / "t.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n[Events]\nFormat: Layer, "
        "Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hi\n",
        encoding="utf-8")
    graph = tmp_path / "g.txt"
    graph.write_text(f"[0:v]subtitles=filename={filter_path(ass)}[out]",
                     encoding="utf-8")
    r = subprocess.run([detect_ffmpeg()[0], "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=s=320x240:d=0.2",
                        "-filter_complex_script", str(graph), "-map", "[out]",
                        "-f", "null", "-"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_a_final_s_episode_number_is_kept(settings):
    from pipeline.room_dressing import episode_number

    a = episode_number(settings, "AAA", "2026-09-01", assign=True)
    b = episode_number(settings, "BBB", "2026-09-02", assign=True)
    assert (a, b) == (1, 2), "two finals before any upload get two numbers"
    assert episode_number(settings, "AAA", "2026-09-01") == 1


def test_scraped_text_cannot_fill_a_later_token(settings, tmp_path):
    from bot.prompts import fill_prompt

    tpl = settings.templates_dir / "master_prompt_headline.md"
    text = fill_prompt("headline", "SPY", None, tmp_path, settings,
                       headline="CPI {{beat_order}} hot", headline_mode="macro")
    assert "CPI {{beat_order}} hot" in text
    assert tpl.exists()


def test_a_move_off_zero_is_a_move():
    from pipeline.standing import Move

    assert Move("net_income", 0.0, -5e8).change == -1.0
    assert Move("net_income", 0.0, 0.0).change == 0.0


def test_a_zero_to_twenty_four_window_is_always_open(settings):
    from pipeline.standing import in_batch_window

    s = settings.model_copy(update={"batch_start_hour": 0, "batch_end_hour": 24})
    assert in_batch_window(s, datetime(2026, 10, 5, 13, 0))


def test_a_short_does_not_overwrite_the_long_s_cover(settings, workspace,
                                                     short_valid_json):
    from pipeline.parser_short import parse_short_script
    from pipeline.thumbnail import make_thumbnail

    ws = Workspace(settings, "EXMPL", "2026-07-01")
    cover = ws.path / "thumbnail.png"
    Image.new("RGB", (1280, 720), (1, 2, 3)).save(cover)
    script, _ = parse_short_script(short_valid_json, settings)
    out = make_thumbnail(script, ws, settings)
    assert out is not None and out.name == "thumbnail_short.png"
    assert Image.open(cover).getpixel((5, 5)) == (1, 2, 3)


def test_an_oversize_thumbnail_is_shrunk_for_youtube(tmp_path):
    import os

    from pipeline.youtube import THUMBNAIL_MAX_BYTES, thumbnail_for_upload

    noisy = Image.frombytes("RGB", (1280, 720), os.urandom(1280 * 720 * 3))
    p = tmp_path / "thumbnail.png"
    noisy.save(p)
    assert p.stat().st_size > THUMBNAIL_MAX_BYTES
    out = thumbnail_for_upload(p)
    assert out.suffix == ".jpg" and out.stat().st_size <= THUMBNAIL_MAX_BYTES


def test_a_second_upload_of_the_same_render_is_refused(core, settings):
    from pipeline.youtube import VideoLog, VideoRecord

    ws = Workspace(settings, "EXMPL", "2026-07-01").create()
    ws.set_lane("long")
    (ws.path / "long_final.mp4").write_bytes(b"x")
    (ws.path / "script_long.json").write_text("{}", encoding="utf-8")
    VideoLog(settings).record(VideoRecord(
        ticker="EXMPL", video_id="v1", title="t", privacy="private",
        workdate="2026-07-01", fmt="long",
        uploaded_at=datetime.now(timezone.utc).isoformat()))
    reply = core.upload_command(["EXMPL", "long"])
    assert "already up" in reply.text and "again" in reply.text


def test_old_finished_job_records_are_pruned(settings):
    import os
    import time

    from pipeline.cleanup import cleanup

    jobs = settings.state_dir / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    old = jobs / "old.json"
    old.write_text(json.dumps({"status": "done"}), encoding="utf-8")
    live = jobs / "live.json"
    live.write_text(json.dumps({"status": "queued"}), encoding="utf-8")
    stale = time.time() - 200 * 86400
    for f in (old, live):
        os.utime(f, (stale, stale))
    cleanup(settings)
    assert not old.exists() and live.exists()


def test_the_ledger_meters_the_billable_text(settings):
    from pipeline.tts import TTSEngine

    eng = TTSEngine(settings)
    assert eng.billable_chars("plain words", "short") == len("plain words")


def test_settings_read_the_checkout_dotenv_from_anywhere():
    from config import BASE_DIR

    files = Settings.model_config["env_file"]
    assert str(BASE_DIR / ".env") in files


def test_scheduled_rows_past_their_time_drop_off(settings):
    from pipeline.youtube import VideoLog, VideoRecord

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    log_ = VideoLog(settings)
    log_.record(VideoRecord(ticker="A", video_id="p", title="p",
                            privacy="scheduled", publish_at=past))
    log_.record(VideoRecord(ticker="B", video_id="f", title="f",
                            privacy="scheduled", publish_at=future))
    assert [v.video_id for v in log_.scheduled()] == ["f"]


def test_a_pair_upload_does_not_send_a_clip_that_is_already_up(core, settings,
                                                              monkeypatch):
    """`/upload T pair` skipped the "already up" guard: run twice, or again
    after the second clip failed, it re-sent every clip under the pair's tag."""
    from types import SimpleNamespace

    import pipeline.youtube as yt
    from pipeline.youtube import VideoLog, VideoRecord

    ws = Workspace(settings, "EXMPL", "2026-07-01").create()
    ws.set_lane("long")
    (ws.path / "long_final.mp4").write_bytes(b"x")
    for n, start in ((1, 30.0), (2, 300.0)):
        clip = ws.path / f"short_repurposed_{n}.mp4"
        clip.write_bytes(b"x")
        clip.with_suffix(".repurpose.json").write_text(
            json.dumps({"window": [start, start + 50]}), encoding="utf-8")
    VideoLog(settings).record(VideoRecord(
        ticker="EXMPL", video_id="v1", title="t", privacy="private",
        workdate="2026-07-01", fmt="clip", clip_start_s=30.0,
        uploaded_at=datetime.now(timezone.utc).isoformat()))
    sent = []
    monkeypatch.setattr(yt, "available", lambda s: (True, ""))
    monkeypatch.setattr(yt, "upload_video", lambda clip, *a, **k: sent.append(
        k["clip_start_s"]) or SimpleNamespace(url=lambda: f"https://y/{clip.name}"))
    monkeypatch.setattr(type(core), "_upload_package", lambda self, *a: object())
    monkeypatch.setattr(type(core), "_render_duration", lambda self, *a: 50.0)

    reply = core.upload_command(["EXMPL", "pair"])
    assert sent == [300.0], reply.text
    assert "already up" in reply.text
    # `again` is the operator saying a second copy is meant
    sent.clear()
    core.upload_command(["EXMPL", "pair", "again"])
    assert sent == [30.0, 300.0]
