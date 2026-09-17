#!/usr/bin/env python3
"""Archive `state/` before you do something risky (P6).

`state/` is the only place several things exist:

  * `spend.json` — the spend ledger. THE ONLY RECORD of what has been spent
    this month, and therefore the only thing enforcing `MONTHLY_SPEND_CAP`.
    Lose it and the cap resets to zero silently, which is the one failure in
    this system that costs money rather than time.
  * `thesis.json` / `confessions.json` / `idea_queue.json` — the standing
    state `/update` grades against and the confession ledger the voice gate
    reads. Lose it and every ticker becomes a first-time take.
  * `published.json` — what has gone to YouTube, so `/upload` does not
    re-upload.
  * `jobs/` — the queue, including anything QUEUED that a restart would
    re-enqueue.
  * `last_digest.json`, `alerts.json`, `earnings_calendar.json` — the
    scheduler's memory of what it has already sent.

None of it is large and none of it is reconstructible.

    python scripts/backup_state.py                 # -> backups/state-<stamp>.tar.gz
    python scripts/backup_state.py --out /mnt/nas  # somewhere else
    python scripts/backup_state.py --list          # what is already archived

NOT A SCHEDULED JOB, deliberately. This is one command that is easy to run
before a risky change; a cron that silently stops is a backup you think you
have. Exit 0 on success, non-zero with a reason otherwise.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DIRNAME = "backups"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n / 1:.0f}{unit}"
        n /= 1024.0
    return f"{n:.0f}GB"


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv: list[str] | None = None) -> int:
    from config import get_settings

    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path,
                    default=Path(settings.base_dir) / DEFAULT_DIRNAME,
                    help=f"where the archive goes (default: <repo>/{DEFAULT_DIRNAME})")
    ap.add_argument("--state", type=Path, default=settings.state_dir,
                    help="the directory to archive (default: STATE_DIR)")
    ap.add_argument("--list", action="store_true",
                    help="list existing archives and exit")
    args = ap.parse_args(argv)

    out: Path = args.out
    if args.list:
        found = sorted(out.glob("state-*.tar.gz")) if out.is_dir() else []
        if not found:
            print(f"No archives in {out}.")
            return 0
        print(f"{len(found)} archive(s) in {out}:")
        for f in found:
            when = datetime.fromtimestamp(f.stat().st_mtime)
            print(f"  {f.name:32s} {_human(f.stat().st_size):>8s}  "
                  f"{when:%Y-%m-%d %H:%M}")
        return 0

    state: Path = args.state
    if not state.is_dir():
        print(f"No state directory at {state} — nothing to back up. That is "
              f"normal on a checkout the bot has never run in.",
              file=sys.stderr)
        return 1
    files = [f for f in state.rglob("*") if f.is_file()]
    if not files:
        print(f"{state} is empty — nothing to back up.", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = out / f"state-{stamp}.tar.gz"
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(state, arcname="state")
    except OSError as e:
        print(f"Could not write {dest}: {e}", file=sys.stderr)
        return 1

    print(f"source  : {state}  ({len(files)} file(s), {_human(_size(state))})")
    print(f"archive : {dest}  ({_human(dest.stat().st_size)})")
    ledger = state / "spend.json"
    if ledger.is_file():
        try:
            import json

            spend = json.loads(ledger.read_text(encoding="utf-8"))
            month = max(spend, default="")
            if month:
                print(f"ledger  : {month} carried through — the spend cap is "
                      f"only as good as this file")
        except (OSError, ValueError):
            pass
    else:
        print("ledger  : no spend.json yet (nothing paid for on this box)")
    print("\nRestore with:  tar -xzf "
          f"{dest} -C {state.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
