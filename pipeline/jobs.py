"""Async job queue with per-job state persisted to disk (§6 jobs.py).

One render at a time by default. The bot event loop is never blocked:
render stages run in a worker thread via `asyncio.to_thread`. Job state
lives in state/jobs/<id>.json so `/status` works across restarts; jobs
that were RUNNING when the process died are marked INTERRUPTED on boot
(re-queuing them is the operator's call — every stage is cache-backed,
so a re-run costs nothing that was already paid for).

Cancellation is cooperative: `/cancel` flips the persisted status and the
executor checks it between stages (TTS -> b-roll -> render -> delivery).
An ffmpeg encode already in flight finishes its stage first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from config import Settings
from pipeline.models import JobKind, JobRecord, JobStatus

log = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]


class JobCancelled(Exception):
    pass


class JobStore:
    def __init__(self, settings: Settings):
        self.dir = settings.state_dir / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def save(self, job: JobRecord) -> None:
        job.touch()
        self.path(job.id).write_text(job.model_dump_json(indent=2))

    def load(self, job_id: str) -> JobRecord | None:
        p = self.path(job_id)
        if not p.exists():
            return None
        return JobRecord.model_validate_json(p.read_text())

    def all(self) -> list[JobRecord]:
        jobs = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                jobs.append(JobRecord.model_validate_json(p.read_text()))
            except Exception:  # never let one corrupt file kill /status
                log.warning("unreadable job file %s", p)
        return jobs

    def mark_interrupted_running(self) -> int:
        n = 0
        for job in self.all():
            if job.status is JobStatus.RUNNING:
                job.status = JobStatus.INTERRUPTED
                job.detail = "process restarted mid-render; re-run to resume from caches"
                self.save(job)
                n += 1
        return n


class RenderJobQueue:
    """Single-worker asyncio queue. `executor` does the blocking work for
    one job (called in a thread); `notifier` posts progress to Telegram."""

    def __init__(
        self,
        settings: Settings,
        executor: Callable[[JobRecord], str],
        notifier: Notifier | None = None,
    ):
        self.settings = settings
        self.store = JobStore(settings)
        self.executor = executor
        self.notifier = notifier
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        interrupted = self.store.mark_interrupted_running()
        if interrupted:
            log.warning("%d job(s) marked INTERRUPTED from a previous run", interrupted)

    # --------------------------------------------------------------- public
    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.get_running_loop().create_task(self._worker_loop())

    async def submit(self, kind: JobKind, ticker: str, workdate: str) -> JobRecord:
        active = [
            j for j in self.store.all()
            if j.ticker == ticker.upper() and j.kind == kind
            and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ]
        if active:
            raise ValueError(f"a {kind.value} job for {ticker} is already {active[0].status.value}")
        job = JobRecord(
            id=uuid.uuid4().hex[:10],
            kind=kind,
            ticker=ticker.upper(),
            workdate=workdate,
        )
        self.store.save(job)
        await self._queue.put(job.id)
        return job

    def cancel(self, ticker: str) -> list[JobRecord]:
        cancelled = []
        for job in self.store.all():
            if job.ticker == ticker.upper() and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                job.status = JobStatus.CANCELLED
                job.detail = "cancelled by operator"
                self.store.save(job)
                cancelled.append(job)
        return cancelled

    def is_cancelled(self, job_id: str) -> bool:
        job = self.store.load(job_id)
        return job is not None and job.status is JobStatus.CANCELLED

    def status_text(self) -> str:
        jobs = self.store.all()
        if not jobs:
            return "No jobs yet."
        recent = sorted(jobs, key=lambda j: j.updated_at, reverse=True)[:10]
        lines = []
        icons = {
            JobStatus.QUEUED: "⏳", JobStatus.RUNNING: "🎬", JobStatus.DONE: "✅",
            JobStatus.FAILED: "❌", JobStatus.CANCELLED: "🚫", JobStatus.INTERRUPTED: "⚡",
        }
        for j in recent:
            line = f"{icons[j.status]} {j.ticker} {j.kind.value} — {j.status.value}"
            if j.detail:
                line += f" ({j.detail})"
            if j.delivered_link:
                line += f"\n    {j.delivered_link}"
            lines.append(line)
        return "\n".join(lines)

    # --------------------------------------------------------------- worker
    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self.store.load(job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                continue  # cancelled while queued (or state file removed)
            job.status = JobStatus.RUNNING
            self.store.save(job)
            await self._notify(f"🎬 {job.ticker}: {job.kind.value} started")
            try:
                artifact = await asyncio.to_thread(self.executor, job)
                job = self.store.load(job_id) or job
                if job.status is JobStatus.CANCELLED:
                    await self._notify(f"🚫 {job.ticker}: cancelled")
                    continue
                job.status = JobStatus.DONE
                job.artifact = artifact
                self.store.save(job)
            except JobCancelled:
                job = self.store.load(job_id) or job
                job.status = JobStatus.CANCELLED
                self.store.save(job)
                await self._notify(f"🚫 {job.ticker}: cancelled")
            except Exception as e:  # report, never crash the worker
                log.exception("job %s failed", job_id)
                job = self.store.load(job_id) or job
                job.status = JobStatus.FAILED
                job.error = str(e)[:1500]
                self.store.save(job)
                await self._notify(f"❌ {job.ticker} {job.kind.value} failed:\n{job.error[:600]}")

    async def _notify(self, text: str) -> None:
        if self.notifier is not None:
            try:
                await self.notifier(text)
            except Exception:
                log.exception("notifier failed")
