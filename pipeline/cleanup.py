"""Disk hygiene: prune heavyweight render artifacts from workspaces
older than RETENTION_DAYS. Caches are NEVER touched (they are what makes
re-runs free), and neither are scripts, approvals, reports or the
company-data exports — those are small and feed the screener cooldown
history.

Run manually or from the shipped systemd timer:

    .venv/bin/python -m pipeline.cleanup [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

from config import Settings, get_settings

log = logging.getLogger(__name__)

PRUNE_FILE_SUFFIXES = {".mp4", ".mov", ".m4a", ".wav"}
PRUNE_DIR_NAMES = {"render_short", "render_long", "render_long_draft", "thumbs"}


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

    # delivered copies are duplicates of what's already archived remotely
    delivered = settings.workspace_dir / "_delivered"
    for ddir in _old_date_dirs(delivered, cutoff):
        freed += sum(p.stat().st_size for p in ddir.rglob("*") if p.is_file())
        removed_dirs += 1
        log.info("prune delivered %s", ddir)
        if not dry_run:
            shutil.rmtree(ddir, ignore_errors=True)

    stats = {
        "cutoff": cutoff.isoformat(),
        "files_removed": removed_files,
        "dirs_removed": removed_dirs,
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
