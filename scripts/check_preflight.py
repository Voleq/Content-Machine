#!/usr/bin/env python3
"""Everything before a first live video that a machine can check (P10).

The full checklist is in the README under "Preflight". Most of it cannot be
automated — steps that spend real money, upload a video, or need someone to
read a YouTube Studio page are the operator's and are not attempted here.
What this covers is the half a script can answer, in one command, so the
answer is not "paste this Python and read the output".

    python scripts/check_preflight.py
    python scripts/check_preflight.py --live   # also check live-mode settings

Exit 0 when every automatable check passes, 1 when one fails. Nothing here
touches the network or spends anything.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS, FAIL, SKIP = "PASS", "FAIL", "----"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, state: str, name: str, detail: str = "") -> None:
        self.rows.append((state, name, detail))

    def render(self) -> int:
        width = max(len(n) for _, n, _ in self.rows)
        for state, name, detail in self.rows:
            print(f"[{state}] {name:<{width}}  {detail}")
        failed = [n for s, n, _ in self.rows if s == FAIL]
        print()
        if not failed:
            print("PREFLIGHT OK — every automatable check passes. The steps "
                  "that spend money, upload a video or need a human to read a "
                  "page are still yours; the README's Preflight section lists "
                  "them in order.")
            return 0
        print(f"BLOCKED — {len(failed)} check(s) failed: "
              f"{', '.join(failed)}", file=sys.stderr)
        print("Each line above says what to run. None of this is a bug to "
              "route around: every one is a build product or a credential "
              "the render path correctly refuses to proceed without.",
              file=sys.stderr)
        return 1


def _kit(settings, report: Report) -> None:
    from pipeline.plates import PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError as e:
        report.add(FAIL, "design kit",
                   f"{str(e)[:80]}… — run `npm install` then "
                   f"`python scripts/ingest_kit.py kit`")
        return
    keys = reg.keys() if callable(getattr(reg, "keys", None)) else []
    report.add(PASS, "design kit",
               f"{len(keys)} plates — now run `/kit doctor`, while the "
               f"host/room change is still fresh")


def _sfx(settings, report: Report) -> None:
    from pipeline.audio_assets import generated_audio

    placeholders = generated_audio(settings)
    if placeholders:
        report.add(FAIL, "sound provenance",
                   f"{len(placeholders)} placeholder(s) block every final "
                   f"render — `scripts/fetch_sfx.py`, then "
                   f"`scripts/check_sfx.py`")
    else:
        report.add(PASS, "sound provenance", "every file attributed")


def _sec_agent(settings, report: Report, live: bool) -> None:
    if settings.sec_user_agent.strip():
        report.add(PASS, "SEC_USER_AGENT", settings.sec_user_agent.strip())
    elif live:
        report.add(FAIL, "SEC_USER_AGENT",
                   "empty — the filing brief, the 8-K source and "
                   "[SHOW FILING] all degrade to nothing, quietly")
    else:
        report.add(SKIP, "SEC_USER_AGENT",
                   "unset; only matters with MOCK_MODE off (--live to check)")


def _broll(settings, report: Report) -> None:
    n = settings.broll_library_size()
    if n:
        report.add(PASS, "owned b-roll", f"{n} clip(s)")
    else:
        report.add(SKIP, "owned b-roll",
                   "empty — every [CLIP] will reach for Pexels, then "
                   "Giphy/Tenor. Not a blocker; it is a legal exposure.")


def _delivery(settings, report: Report, live: bool) -> None:
    backend = settings.delivery_backend
    if backend == "local" and live:
        report.add(FAIL, "DELIVERY_BACKEND",
                   "`local` writes a file path and no link — correct for "
                   "testing, silently useless in production")
    else:
        report.add(PASS, "DELIVERY_BACKEND", backend)


def _publish_window(settings, report: Report) -> None:
    """Not a pass/fail — a decision the operator should have made."""
    report.add(SKIP, "publish window",
               f"{settings.publish_hour:02d}:{settings.publish_minute:02d} "
               f"{settings.publish_timezone} — decide this rather than "
               f"inherit it (that is 10:00 US Eastern in summer)")


def _engine(settings, report: Report) -> None:
    engine = settings.long_render_engine
    if engine == "segments":
        report.add(PASS, "LONG engine", "segments (the production path)")
    else:
        report.add(FAIL, "LONG engine",
                   f"{engine!r} — `shots` is wired up and has no production "
                   f"mileage. Do not pick it for a first live LONG.")


def _state_backup(settings, report: Report) -> None:
    backups = Path(settings.base_dir) / "backups"
    found = sorted(backups.glob("state-*.tar.gz")) if backups.is_dir() else []
    if found:
        report.add(PASS, "state backup", f"{len(found)}, newest {found[-1].name}")
    else:
        report.add(SKIP, "state backup",
                   "none yet — `python scripts/backup_state.py` before "
                   "anything risky; the ledger is the only record of spend")


def _suite(report: Report) -> None:
    """The suite is the baseline everything else assumes."""
    report.add(SKIP, "test suite",
               "run `pytest -m 'not audio_provenance'` yourself — it takes "
               "~25 minutes and this script should not")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true",
                    help="also check the settings that only matter with "
                         "MOCK_MODE off")
    args = ap.parse_args(argv)

    from config import get_settings

    settings = get_settings()
    live = args.live or not settings.mock_mode

    print(f"MOCK_MODE     : {settings.mock_mode}"
          f"{'' if live else '   (--live to check production settings)'}")
    print(f"assets        : {settings.assets_dir}")
    print(f"state         : {settings.state_dir}\n")

    report = Report()
    _kit(settings, report)
    _sfx(settings, report)
    _sec_agent(settings, report, live)
    _broll(settings, report)
    _delivery(settings, report, live)
    _engine(settings, report)
    _publish_window(settings, report)
    _state_backup(settings, report)
    _suite(report)
    return report.render()


if __name__ == "__main__":
    raise SystemExit(main())
