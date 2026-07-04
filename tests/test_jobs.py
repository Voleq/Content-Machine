import asyncio

import pytest

from pipeline.jobs import JobStore, RenderJobQueue
from pipeline.models import JobKind, JobRecord, JobStatus


async def _wait_status(store: JobStore, job_id: str, statuses, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        job = store.load(job_id)
        if job and job.status in statuses:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"job never reached {statuses}")


async def test_job_lifecycle_success(settings):
    done = []

    def executor(job: JobRecord) -> str:
        done.append(job.id)
        return f"/renders/{job.ticker}.mp4"

    notes = []

    async def notifier(text):
        notes.append(text)

    q = RenderJobQueue(settings, executor, notifier)
    q.start()
    job = await q.submit(JobKind.RENDER_SHORT, "exmpl", "2026-07-01")
    final = await _wait_status(q.store, job.id, {JobStatus.DONE})
    assert final.artifact == "/renders/EXMPL.mp4"
    assert done == [job.id]
    assert any("started" in n for n in notes)
    assert "EXMPL" in q.status_text()


async def test_duplicate_submit_rejected(settings):
    started = asyncio.Event()
    release = asyncio.Event()

    def executor(job):
        started.set()
        # block the single worker until released (executor runs in a thread)
        import time
        while not release.is_set():
            time.sleep(0.02)
        return "x"

    q = RenderJobQueue(settings, executor)
    q.start()
    await q.submit(JobKind.RENDER_LONG, "ABC", "2026-07-01")
    await started.wait()
    with pytest.raises(ValueError, match="already"):
        await q.submit(JobKind.RENDER_LONG, "ABC", "2026-07-01")
    release.set()


async def test_cancel_queued_job_never_runs(settings):
    ran = []

    def executor(job):
        ran.append(job.id)
        return "x"

    q = RenderJobQueue(settings, executor)
    # cancel BEFORE starting the worker: job is still queued
    job = await q.submit(JobKind.RENDER_SHORT, "ABC", "2026-07-01")
    cancelled = q.cancel("abc")
    assert [j.id for j in cancelled] == [job.id]
    q.start()
    await asyncio.sleep(0.3)
    assert ran == []
    assert q.store.load(job.id).status is JobStatus.CANCELLED


async def test_failed_job_reports(settings):
    def executor(job):
        raise RuntimeError("ffmpeg exploded")

    notes = []

    async def notifier(text):
        notes.append(text)

    q = RenderJobQueue(settings, executor, notifier)
    q.start()
    job = await q.submit(JobKind.RENDER_SHORT, "BAD", "2026-07-01")
    final = await _wait_status(q.store, job.id, {JobStatus.FAILED})
    assert "ffmpeg exploded" in final.error
    assert any("failed" in n for n in notes)


async def test_interrupted_marking_on_boot(settings):
    store = JobStore(settings)
    job = JobRecord(id="zzz", kind=JobKind.RENDER_LONG, ticker="X", workdate="2026-07-01",
                    status=JobStatus.RUNNING)
    store.save(job)

    q = RenderJobQueue(settings, lambda j: "x")
    reloaded = q.store.load("zzz")
    assert reloaded.status is JobStatus.INTERRUPTED
    assert "restart" in reloaded.detail
