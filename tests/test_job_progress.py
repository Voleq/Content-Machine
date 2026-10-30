"""The page's render step: how far a job is, and its own log (pipeline/jobs)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from pipeline import jobs
from pipeline.jobs import job_log, progress, run_logged
from pipeline.models import JobKind, JobRecord

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_detail_fraction_to_percent():
    # the long's beats are encoded once Dennis is drawn: the last stretch
    p = progress({"status": "running", "detail": "render 20/40 segments"}, now=NOW)
    assert p["stage"] == "render" and p["pct"] == 85.5
    assert progress({"status": "running", "detail": "proof 40/40 segments"},
                    now=NOW)["pct"] == 96.0
    assert progress({"status": "running", "detail": "tts"}, now=NOW)["pct"] == 0.0
    queued = progress({"status": "queued", "detail": ""}, now=NOW)
    assert (queued["stage"], queued["pct"], queued["eta_s"]) == ("queued", 0, None)
    assert queued["words"] == "Waiting its turn in the queue"


def test_a_short_says_which_of_its_stages_it_is_in():
    """His proof said nothing while it rendered (30 Oct 2026): a short's cut
    sat on "render" at 12% from start to finish."""
    frames = progress({"status": "running", "detail": "frames 900/1800"}, now=NOW)
    assert frames["pct"] == 83.5 and (frames["done"], frames["total"]) == (900, 1800)
    assert frames["words"].startswith("Putting every frame")
    # Dennis's frames count up shot by shot: the job's bar moves by where
    # the shot is in the video, and holds where that is not said rather
    # than run back at the next shot.
    him = progress({"status": "running", "detail": "dennis 30/91 · shot 2 of 4, desk-wide"},
                   now=NOW)
    assert him["pct"] == round(12 + 63 * (1 + 30 / 91) / 4, 1)
    assert (him["done"], him["total"]) == (30, 91)
    assert him["note"] == "shot 2 of 4, desk-wide" and "3D" in him["words"]
    beat = progress({"status": "running", "detail": "dennis 91/91 · beat 40 of 40, wide"},
                    now=NOW)
    assert beat["pct"] == 75.0                   # where the long's beats take over
    assert progress({"status": "running", "detail": "dennis 30/91 · shot 2, wide"},
                    now=NOW)["pct"] == 12.0
    # A final's delivery is the end of the bar, not its start.
    assert progress({"status": "running", "detail": "delivery"}, now=NOW)["pct"] == 96.0


def test_reports_reach_the_running_job_and_no_other(monkeypatch):
    got = []
    clock = iter([0.0, 1.0, 3.5, 5.5, 6.0, 6.2])
    monkeypatch.setattr(jobs.time, "monotonic", lambda: next(clock))
    jobs.report("frames", 1, 10)                 # no job on this thread: nowhere
    with jobs.reporting(got.append, every_s=3.0):
        jobs.report("frames", 1, 10)             # the first of a stage
        jobs.report("frames", 2, 10)             # too soon
        jobs.report("frames", 5, 10)             # 3 s on
        jobs.report("encode", 0, 1)              # a new stage, at once
        jobs.report("encode", 1, 1)              # the last of one, at once
        jobs.report("dennis", 3, 9, "shot 1")
    jobs.report("frames", 9, 10)
    assert got == ["frames 1/10", "frames 5/10", "encode 0/1", "encode 1/1",
                   "dennis 3/9 · shot 1"]


def test_eta_from_the_estimate():
    started = _iso(NOW - timedelta(minutes=1))
    early = progress({"status": "running", "detail": "tts", "started_at": started},
                     est_render_min=10, now=NOW)
    assert early["eta_s"] == 540
    # Once the cut is under way its own pace decides: 85.5% in 9 minutes.
    later = progress({"status": "running", "detail": "render 20/40 segments",
                      "started_at": _iso(NOW - timedelta(minutes=9))},
                     est_render_min=10, now=NOW)
    assert later["eta_s"] == round(540 * 14.5 / 85.5)
    assert progress({"status": "running", "detail": "tts"}, now=NOW)["eta_s"] is None


def test_job_log_keeps_only_its_thread(settings, monkeypatch):
    settings = settings.model_copy(update={"fred_api_key": "fredsecret123"})
    log = logging.getLogger("pipeline.render_test")
    log.setLevel(logging.INFO)
    job = JobRecord(id="abc123def0", kind=JobKind.RENDER_SHORT, ticker="EXMPL",
                    workdate="2026-10-18")
    monkeypatch.setattr(jobs, "LOG_KEEP", 5)

    def other():
        log.info("from someone else")

    def executor(_job):
        t = threading.Thread(target=other)
        t.start()
        t.join()
        for i in range(8):
            log.info("segment %d", i)
        log.info("GET https://api.stlouisfed.org/x?series=GDP&api_key=fredsecret123")
        return "out.mp4"

    assert run_logged(settings, job, executor) == "out.mp4"
    lines = job_log(settings, job.id, 50)
    assert len(lines) == 5
    assert "segment 7" in lines[-2]
    assert not any("someone else" in x for x in lines)
    assert "fredsecret123" not in lines[-1] and "api_key=•••" in lines[-1]
    assert job_log(settings, "../panel_token") == []
