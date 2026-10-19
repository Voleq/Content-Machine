"""A7: one sentence said again and cut into the voice."""

import json

import pytest

from pipeline.models import WordTimestamp
from pipeline.render_common import ffprobe_duration
from pipeline.tts import TTSEngine
from pipeline.voice_redo import (MAX_REDOS, RedoRefused, _cut_points,
                                 redo_sentence, redos_done, sentences,
                                 splice_words)

TEXT = ("The first sentence is here. The second one is the bad one. "
        "And a third to finish.")


def _w(word, start, end, a):
    return WordTimestamp(word=word, start=start, end=end, char_start=a,
                         char_end=a + len(word))


def test_sentence_window_and_shift():
    words = [_w("One.", 0.2, 0.6, 0), _w("Two", 1.0, 1.3, 5),
             _w("words.", 1.4, 1.9, 9), _w("Three.", 2.5, 3.0, 16)]
    text = "One. Two words. Three."
    rows = sentences(words, text)
    cut_a, cut_b = _cut_points(rows, 1, 3.5)
    assert (cut_a, cut_b) == pytest.approx((0.8, 2.2))
    frag = [_w("Two", 0.3, 0.6, 0), _w("words.", 0.7, 1.5, 4)]
    new, window, dur = splice_words(words, frag, rows, 1, 3.5, cut_a, cut_b)
    assert [w.word for w in new] == ["One.", "Two", "words.", "Three."]
    # the pause before the sentence keeps its length
    assert new[1].start == pytest.approx(cut_a + (1.0 - 0.8))
    # the take is 0.4 s longer than the line it replaced, so Three moves 0.4 s
    assert new[3].start - words[3].start == pytest.approx(dur - 3.5)
    assert [w.char_start for w in new] == [0, 5, 9, 16]


def test_first_and_last_sentence_cut_at_the_edges():
    words = [_w("One.", 0.2, 0.6, 0), _w("Two.", 1.0, 1.4, 5)]
    rows = sentences(words, "One. Two.")
    assert _cut_points(rows, 0, 2.0)[0] == 0.0
    assert _cut_points(rows, 1, 2.0)[1] == 2.0


@pytest.fixture()
def voiced(settings, tmp_path):
    engine = TTSEngine(settings)
    engine.synthesize(TEXT, "long")
    ws = tmp_path / "ws"
    ws.mkdir()
    return engine, ws


@pytest.mark.parametrize("index", [1, 2, 3])
def test_redo_splices_and_keeps_the_original(settings, voiced, index):
    engine, ws = voiced
    cdir = engine.voice_dir(TEXT, "long")
    before = ffprobe_duration(cdir / "audio.m4a")
    res = redo_sentence(engine, settings, text=TEXT, fmt="long", events=None,
                        index=index, ticker="EXMPL", ws_path=ws)
    assert res.left == MAX_REDOS - 1
    assert (cdir / "audio.orig.m4a").exists()
    after = ffprobe_duration(cdir / "audio.m4a")
    assert after == pytest.approx(res.new_s) and before == pytest.approx(res.old_s)
    words = json.loads((cdir / "words.json").read_text(encoding="utf-8"))
    assert [w["word"] for w in words] == TEXT.split()
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)
    assert words[-1]["end"] <= after + 0.05
    assert redos_done(ws, "long")[0]["index"] == index


def test_a_second_redo_is_a_new_take(settings, voiced):
    engine, ws = voiced
    redo_sentence(engine, settings, text=TEXT, fmt="long", events=None,
                  index=2, ticker="EXMPL", ws_path=ws)
    redo_sentence(engine, settings, text=TEXT, fmt="long", events=None,
                  index=2, ticker="EXMPL", ws_path=ws)
    assert [r["take"] for r in redos_done(ws, "long")] == [1, 2]


def test_cap_of_ten(settings, voiced):
    engine, ws = voiced
    (ws / "voice_redos_long.json").write_text(json.dumps(
        [{"index": 1, "text": "x"}] * MAX_REDOS), encoding="utf-8")
    with pytest.raises(RedoRefused, match="all 10"):
        redo_sentence(engine, settings, text=TEXT, fmt="long", events=None,
                      index=1, ticker="EXMPL", ws_path=ws)


def test_no_voice_no_redo(settings, tmp_path):
    with pytest.raises(RedoRefused, match="no voice"):
        redo_sentence(TTSEngine(settings), settings, text="Never voiced.",
                      fmt="long", events=None, index=1, ticker="EXMPL",
                      ws_path=tmp_path)


def test_out_of_range(settings, voiced):
    engine, ws = voiced
    with pytest.raises(RedoRefused, match="no sentence 9"):
        redo_sentence(engine, settings, text=TEXT, fmt="long", events=None,
                      index=9, ticker="EXMPL", ws_path=ws)


def test_a_running_render_is_stopped_to_start_again(settings, workspace):
    from types import SimpleNamespace

    from bot.handlers import BotCore
    from pipeline.jobs import JobStore
    from pipeline.models import JobKind, JobRecord, JobStatus
    from pipeline.workspace import Workspace

    core = BotCore(settings)
    store = JobStore(settings)
    core.queue = SimpleNamespace(store=store)
    for i, (kind, status) in enumerate([
            (JobKind.RENDER_LONG, JobStatus.RUNNING),
            (JobKind.RENDER_SHORT, JobStatus.QUEUED),
            (JobKind.RENDER_LONG, JobStatus.DONE)]):
        store.save(JobRecord(id=f"j{i}", kind=kind, ticker="EXMPL",
                             workdate="2026-07-01", status=status))
    ws = Workspace(settings, "EXMPL", "2026-07-01")
    assert core._stop_renders_of(ws, "long") == [
        (JobKind.RENDER_LONG, "EXMPL", "2026-07-01")]
    assert store.load("j0").status is JobStatus.CANCELLED
    assert store.load("j1").status is JobStatus.QUEUED
