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
import logging
import threading
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from config import Settings
from pipeline import journal
from pipeline.models import JobKind, JobRecord, JobStatus

log = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]


class JobCancelled(Exception):
    pass


def _journal(settings: Settings, job: JobRecord, what: str, **data) -> None:
    """One journal line for a job changing state."""
    journal.note(settings, "job", f"{job.kind.value} {what}",
                 ticker=job.ticker, workdate=job.workdate, job_id=job.id,
                 job_kind=job.kind.value, status=job.status.value, **data)


class _NotQueued(Exception):
    """A transition that no longer applies: the job moved on under us."""


def _start(job: JobRecord) -> None:
    if job.status is not JobStatus.QUEUED:
        raise _NotQueued
    job.status = JobStatus.RUNNING


def _cancelled(job: JobRecord) -> None:
    job.status = JobStatus.CANCELLED


class JobStore:
    """One JSON file per job, written atomically, read-modify-written under
    one lock.

    The render worker's `checkpoint` (a thread) and `/cancel` (the event
    loop) both load a job, change it and save it. Unlocked, a checkpoint that
    loaded RUNNING just before a cancel saved CANCELLED wrote RUNNING back
    over it, and the cancel was lost. And a plain `write_text` let `/status`
    or `submit()` read half a file, skip it as unreadable, and accept a
    duplicate render.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dir = settings.state_dir / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Called with a copy of every job saved, from whichever thread saved
        # it: the video cards edit themselves off this (`CardBoard`). A
        # listener that raises is logged and never fails the save.
        self.listeners: list = []

    def path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def save(self, job: JobRecord) -> None:
        with self._lock:
            job.touch()
            p = self.path(job.id)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(p)
            snapshot = job.model_copy() if self.listeners else None
        for listener in list(self.listeners):
            try:
                listener(snapshot)
            except Exception:  # noqa: BLE001 - a card is never the job
                log.exception("job listener failed")

    def update(self, job_id: str, change) -> JobRecord | None:
        """Load, `change(job)`, save — as one step. `change` may raise to
        abandon the update (nothing is written)."""
        with self._lock:
            job = self.load(job_id)
            if job is None:
                return None
            change(job)
            self.save(job)
            return job

    def load(self, job_id: str) -> JobRecord | None:
        p = self.path(job_id)
        if not p.exists():
            return None
        return JobRecord.model_validate_json(p.read_text(encoding="utf-8"))

    def all(self) -> list[JobRecord]:
        jobs = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                jobs.append(JobRecord.model_validate_json(p.read_text(encoding="utf-8")))
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
                _journal(self.settings, job, "interrupted by a restart")
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
        self._loop: asyncio.AbstractEventLoop | None = None
        interrupted = self.store.mark_interrupted_running()
        if interrupted:
            log.warning("%d job(s) marked INTERRUPTED from a previous run", interrupted)

    # --------------------------------------------------------------- public
    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._loop = asyncio.get_running_loop()
            self._worker_task = self._loop.create_task(self._worker_loop())
        self.requeue_persisted()

    def requeue_persisted(self) -> int:
        """Put jobs that were QUEUED when the process stopped back on the
        queue (F1).

        `self._queue` is in-memory and starts empty, and
        `mark_interrupted_running()` rescues only RUNNING jobs — so a job
        that was merely QUEUED stayed QUEUED on disk forever and never ran.
        Worse, `submit()` refuses a new job while one is QUEUED or RUNNING,
        so `/render` for that ticker was refused until the operator found
        `/cancel`. On a desktop render box that sleeps, that is routine.

        Re-enqueueing rather than marking them interrupted, because every
        stage is cache-resumable — so re-running is cheap and correct — and
        because it is what makes `/batch` work as documented: queue a night's
        worth, and a restart does not silently empty it.
        """
        n = 0
        for job in sorted(self.store.all(), key=lambda j: j.created_at):
            if job.status is JobStatus.QUEUED:
                self._queue.put_nowait(job.id)
                n += 1
        if n:
            log.info("re-enqueued %d job(s) left QUEUED by a previous run", n)
        return n

    def notify_sync(self, text: str) -> None:
        """Notify from a worker THREAD. No-op without a running loop."""
        if self.notifier is None or self._loop is None:
            log.warning("operator notice (undelivered): %s", text)
            return
        asyncio.run_coroutine_threadsafe(self._notify(text), self._loop)

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
        _journal(self.settings, job, "queued")
        await self._queue.put(job.id)
        return job

    def cancel(self, ticker: str) -> list[JobRecord]:
        cancelled = []
        for job in self.store.all():
            if job.ticker != ticker.upper() or job.status not in (
                    JobStatus.QUEUED, JobStatus.RUNNING):
                continue

            def _cancel(j: JobRecord) -> None:
                j.status = JobStatus.CANCELLED
                j.detail = "cancelled by operator"

            done = self.store.update(job.id, _cancel)
            if done is not None:
                _journal(self.settings, done, "cancelled by the operator")
                cancelled.append(done)
        return cancelled

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
            # `.get`, because /status is the command an operator runs when
            # something has gone wrong: a status this build has no icon for
            # — a job record written by a newer one — must not be what makes
            # the listing itself raise.
            line = (f"{icons.get(j.status, '•')} {j.ticker} {j.kind.value} "
                    f"— {j.status.value}")
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
            # Every transition is a read-change-write under the store's lock,
            # as `/cancel` and the render's checkpoint thread do theirs: a
            # load here and a save later wrote back whatever this copy held
            # over a change saved in between.
            try:
                job = self.store.update(job_id, _start)
            except _NotQueued:
                job = None
            if job is None:
                continue  # cancelled while queued (or state file removed)
            _journal(self.settings, job, "started")
            await self._notify(f"🎬 {job.ticker}: {job.kind.value} started")
            try:
                artifact = await asyncio.to_thread(self.executor, job)

                def _finish(j: JobRecord) -> None:
                    if j.status is JobStatus.CANCELLED and not j.delivered_link:
                        raise _NotQueued  # a cancel that beat the delivery
                    if j.status is JobStatus.CANCELLED:
                        # The cancel landed after the delivery did: the video
                        # is out and the thesis pinned, so "cancelled" would
                        # be the one thing the record got wrong.
                        j.detail = "delivered before the cancel landed"
                    j.status = JobStatus.DONE
                    j.artifact = artifact

                try:
                    job = self.store.update(job_id, _finish) or job
                except _NotQueued:
                    await self._notify(f"🚫 {job.ticker}: cancelled")
                    continue
                _journal(self.settings, job, "finished", artifact=artifact,
                         link=job.delivered_link)
                # Success was the one outcome that sent nothing. A render
                # started, failed or was cancelled all pushed; a render that
                # WORKED had to be discovered by polling /status, which is how
                # a finished video sat unnoticed for hours.
                await self._notify(self._done_text(job))
            except JobCancelled:
                job = self.store.update(job_id, _cancelled) or job
                _journal(self.settings, job, "cancelled mid-run")
                await self._notify(f"🚫 {job.ticker}: cancelled")
            except Exception as e:  # report, never crash the worker
                log.exception("job %s failed", job_id)
                error = str(e)[:1500]

                def _failed(j: JobRecord) -> None:
                    j.status = JobStatus.FAILED
                    j.error = error

                job = self.store.update(job_id, _failed) or job
                _journal(self.settings, job, f"failed: {job.error[:200]}")
                await self._notify(self._failed_text(job))

    def _done_text(self, job: JobRecord) -> str:
        """The success push. Always names the output path.

        "Done" on its own sends the operator back to /status to find out what
        was produced and where — which is the polling this replaced.
        """
        lines = [f"✅ {job.ticker}: {job.kind.value} done"]
        if job.artifact:
            path = Path(job.artifact)
            lines.append(str(path))
            try:
                mb = path.stat().st_size / 1_000_000
                lines.append(f"{mb:.1f} MB")
            except OSError:
                pass
        if job.delivered_link:
            lines.append(job.delivered_link)
        if job.byproducts:
            lines.append("")
            lines.extend(job.byproducts)
        banner = self.settings.mock_banner()
        if banner:
            lines.append(banner)
        return "\n".join(lines)

    def _failed_text(self, job: JobRecord) -> str:
        """The failure push. Names the workspace so the artifacts are findable."""
        lines = [f"❌ {job.ticker} {job.kind.value} failed:", job.error[:600]]
        ws = self.settings.workspace_dir / job.ticker / job.workdate
        lines.append(f"workspace: {ws}")
        return "\n".join(lines)

    async def _notify(self, text: str) -> None:
        if self.notifier is not None:
            try:
                await self.notifier(text)
            except Exception:
                log.exception("notifier failed")
