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
    p = progress({"status": "running", "detail": "render 20/40 segments"}, now=NOW)
    assert p["stage"] == "render" and p["pct"] == 54.0
    assert progress({"status": "running", "detail": "proof 40/40 segments"},
                    now=NOW)["pct"] == 96.0
    assert progress({"status": "running", "detail": "tts"}, now=NOW)["pct"] == 0.0
    assert progress({"status": "queued", "detail": ""}, now=NOW) == {
        "stage": "queued", "pct": 0, "eta_s": None}


def test_eta_from_the_estimate():
    started = _iso(NOW - timedelta(minutes=1))
    early = progress({"status": "running", "detail": "tts", "started_at": started},
                     est_render_min=10, now=NOW)
    assert early["eta_s"] == 540
    # Once the cut is under way its own pace decides: 54% in 9 minutes.
    later = progress({"status": "running", "detail": "render 20/40 segments",
                      "started_at": _iso(NOW - timedelta(minutes=9))},
                     est_render_min=10, now=NOW)
    assert later["eta_s"] == round(540 * 46 / 54)
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
