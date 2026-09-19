"""Shipping two clips from one long, and finding out which one worked.

`/repurpose` has always picked two or three non-overlapping windows out of a
finished LONG and shipped one of them. The others were thrown away. That is
the only free experiment surface in this pipeline: two clips off the same
render cost no voice generation, no fetches and no new composition, and they
differ in exactly one thing — which minute of the argument they carry.

So they get shipped as a pair, tagged, and compared once both have views
against them. The comparison is deliberately thin: two clips is two clips, and
the honest thing to report is the difference and the denominator, not a
significance claim.

The pair id rides on the video record, which is a dataclass reconstructed
from JSON with `VideoRecord(**row)` — a field with a default reads an old row
that has never heard of it, which is why this could be added without a
migration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import Settings

log = logging.getLogger(__name__)


def pair_id(ticker: str, workdate: str) -> str:
    """The tag both clips off one long share."""
    return f"{ticker.upper()}/{workdate}"


@dataclass
class Arm:
    """One clip in an experiment."""

    video_id: str
    title: str
    start_s: float
    hold: float | None

    def line(self) -> str:
        held = "no views yet" if self.hold is None else f"{self.hold * 100:.1f}%"
        return f"  at {self.start_s:6.1f}s  {held:>12}  {self.title[:44]}"


@dataclass
class Experiment:
    """Two or more clips cut from one long, and how they did."""

    pair: str
    arms: list[Arm]

    @property
    def decided(self) -> bool:
        return sum(1 for a in self.arms if a.hold is not None) >= 2

    @property
    def winner(self) -> Arm | None:
        scored = [a for a in self.arms if a.hold is not None]
        return max(scored, key=lambda a: a.hold) if scored else None

    def line(self) -> str:
        head = f"🅰🅱 {self.pair} — {len(self.arms)} clips off one render"
        rows = [a.line() for a in sorted(self.arms, key=lambda a: a.start_s)]
        if not self.decided:
            rows.append("  Not decided yet: two clips need views against "
                        "both before the difference means anything.")
            return "\n".join([head, *rows])
        best = self.winner
        spread = (max(a.hold for a in self.arms if a.hold is not None)
                  - min(a.hold for a in self.arms if a.hold is not None))
        rows.append(f"  The {best.start_s:.0f}s clip held best, by "
                    f"{spread * 100:.1f} points. One pair is a hint, not a "
                    f"finding — it is worth something once several agree.")
        return "\n".join([head, *rows])


def experiments(settings: Settings) -> list[Experiment]:
    """Every clip pair that has been shipped, newest first."""
    from pipeline.youtube import VideoLog

    by_pair: dict[str, list[Arm]] = {}
    for record in VideoLog(settings).all():
        tag = getattr(record, "experiment", "")
        if not tag:
            continue
        rows = (record.retention or {}).get("rows") or []
        ratios = [float(r["watch_ratio"]) for r in rows
                  if isinstance(r, dict)
                  and isinstance(r.get("watch_ratio"), (int, float))]
        by_pair.setdefault(tag, []).append(Arm(
            video_id=record.video_id, title=record.title,
            start_s=float(getattr(record, "clip_start_s", 0.0) or 0.0),
            hold=(sum(ratios) / len(ratios)) if ratios else None))
    out = [Experiment(pair=tag, arms=arms)
           for tag, arms in by_pair.items() if len(arms) > 1]
    return sorted(out, key=lambda e: e.pair, reverse=True)


def experiments_text(settings: Settings) -> str:
    rows = experiments(settings)
    if not rows:
        return ("No clip pairs shipped yet. /repurpose cuts two or three clips out "
                "of one long; /upload TICKER pair ships two of them tagged, "
                "which costs nothing beyond the second upload and is the only "
                "free experiment this pipeline has.")
    return "\n\n".join(e.line() for e in rows[:6])
