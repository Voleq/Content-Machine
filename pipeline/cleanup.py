"""Disk hygiene: prune heavyweight render artifacts from workspaces
older than RETENTION_DAYS. Scripts, approvals, reports and the company-data
exports are never touched — they are small and feed the screener cooldown
history.

THE VOICE CACHE IS NEVER TOUCHED: it is paid for, and it is what makes a
re-render free. The other caches are rebuildable at the cost of CPU only —
segment clips, the 3D Dennis's shots — and are pruned after
CACHE_RETENTION_DAYS without a write, because nothing else ever bounded them
and the 3D shots alone are a PNG per frame of him.

`_delivered/` is only ever written by the LOCAL delivery backend (and by
MOCK_MODE, which forces it), and there it is the only copy of the finished
video. It is kept unless DELIVERED_RETENTION_DAYS says otherwise.

Run manually or from the shipped systemd timer:

    .venv/bin/python -m pipeline.cleanup [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

from config import Settings, get_settings

log = logging.getLogger(__name__)

PRUNE_FILE_SUFFIXES = {".mp4", ".mov", ".m4a", ".wav"}
PRUNE_DIR_NAMES = {"render_short", "render_long", "render_long_draft",
                   "render_long_proof", "render_long_preview", "thumbs"}
# Caches that cost only CPU to rebuild, pruned by the age of their last
# write. `tts/` is deliberately absent: it is paid for.
REBUILDABLE_CACHES = ("segments", "dennis3d")
# A job record in one of these states is history, and old history goes.
FINISHED_JOB_STATES = ("done", "failed", "cancelled", "interrupted")


def _old_date_dirs(root: Path, cutoff: date) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for tdir in sorted(root.iterdir()):
        if not tdir.is_dir() or tdir.name.startswith("_"):
            continue
        for ddir in sorted(tdir.iterdir()):
            if not ddir.is_dir():
                continue
            try:
                if date.fromisoformat(ddir.name) < cutoff:
                    out.append(ddir)
            except ValueError:
                continue
    return out


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _newest_write(path: Path) -> float:
    """The latest mtime of `path` or anything inside it."""
    newest = path.stat().st_mtime
    if path.is_dir():
        for p in path.rglob("*"):
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                continue
    return newest


def _prune_cache(settings: Settings, dry_run: bool) -> tuple[int, int]:
    """(entries removed, bytes freed) across the rebuildable caches."""
    days = int(getattr(settings, "cache_retention_days", 0) or 0)
    if days <= 0:
        return 0, 0
    cutoff = time.time() - days * 86400
    removed = freed = 0
    for name in REBUILDABLE_CACHES:
        root = Path(settings.cache_dir) / name
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.suffix == ".log":
                continue
            try:
                if _newest_write(entry) >= cutoff:
                    continue
                size = _size(entry)
            except OSError:
                continue
            removed += 1
            freed += size
            log.info("prune cache %s", entry)
            if not dry_run:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
    return removed, freed


def _prune_jobs(settings: Settings, dry_run: bool) -> int:
    """Old finished job records. `JobStore.all()` reads every one of them
    on each `/status` and each submit, so they cannot grow for ever."""
    import json

    days = int(getattr(settings, "jobs_retention_days", 0) or 0)
    jobs = Path(settings.state_dir) / "jobs"
    if days <= 0 or not jobs.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for f in sorted(jobs.glob("*.json")):
        try:
            if f.stat().st_mtime >= cutoff:
                continue
            status = str(json.loads(f.read_text(encoding="utf-8")).get("status", ""))
        except (OSError, ValueError, AttributeError):
            continue
        if status not in FINISHED_JOB_STATES:
            continue
        removed += 1
        if not dry_run:
            f.unlink(missing_ok=True)
    return removed


def cleanup(settings: Settings, dry_run: bool = False) -> dict:
    cutoff = date.today() - timedelta(days=settings.retention_days)
    removed_files = 0
    removed_dirs = 0
    freed = 0

    for ddir in _old_date_dirs(settings.workspace_dir, cutoff):
        for path in list(ddir.rglob("*")):
            if path.is_file() and path.suffix.lower() in PRUNE_FILE_SUFFIXES:
                freed += path.stat().st_size
                removed_files += 1
                log.info("prune file %s", path)
                if not dry_run:
                    path.unlink()
        for name in PRUNE_DIR_NAMES:
            sub = ddir / name
            if sub.is_dir():
                freed += sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
                removed_dirs += 1
                log.info("prune dir %s", sub)
                if not dry_run:
                    shutil.rmtree(sub, ignore_errors=True)

    # `_delivered/` is the local backend's ONLY copy — kept unless asked.
    delivered_days = int(getattr(settings, "delivered_retention_days", 0) or 0)
    if delivered_days > 0:
        delivered = settings.workspace_dir / "_delivered"
        d_cutoff = date.today() - timedelta(days=delivered_days)
        for ddir in _old_date_dirs(delivered, d_cutoff):
            freed += sum(p.stat().st_size for p in ddir.rglob("*") if p.is_file())
            removed_dirs += 1
            log.info("prune delivered %s", ddir)
            if not dry_run:
                shutil.rmtree(ddir, ignore_errors=True)

    cache_removed, cache_freed = _prune_cache(settings, dry_run)
    freed += cache_freed
    jobs_removed = _prune_jobs(settings, dry_run)

    stats = {
        "cutoff": cutoff.isoformat(),
        "files_removed": removed_files,
        "dirs_removed": removed_dirs,
        "cache_entries_removed": cache_removed,
        "job_records_removed": jobs_removed,
        "freed_mb": round(freed / 1e6, 1),
        "dry_run": dry_run,
    }
    log.info("cleanup: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = cleanup(get_settings(), dry_run=args.dry_run)
    print(stats)


if __name__ == "__main__":
    main()
