"""A look at the web panel with nothing real behind it (MOCK_MODE).

Seeds a throwaway folder through the bot's own intake — the fixture workbook
for "Example Corp (EXMPL)", the fixture SHORT script, an approval, a stand-in
proof clip and two fault notes — and serves the panel on it, so the page can
be opened (or screenshotted by `scripts/panel_screens.mjs`) without the
render box, its keys or its videos. Nothing here reads `.env`.

    python scripts/panel_demo.py [FOLDER] [PORT]

Prints the panel's link with its key, then serves until stopped.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.feed import Feed  # noqa: E402
from bot.handlers import BotCore  # noqa: E402
from bot.panel import start_panel  # noqa: E402
from config import Settings  # noqa: E402
from pipeline.alerts import EarningsCalendar, Watchlist  # noqa: E402
from pipeline.standing import IdeaQueue  # noqa: E402
from pipeline.workspace import Workspace  # noqa: E402
from pipeline.youtube import VideoLog, VideoRecord  # noqa: E402

CHAT = 1
FIX = ROOT / "fixtures"


def seed(core: BotCore) -> None:
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx",
                       (FIX / "company_data" / "dennis_data.xlsx").read_bytes())
    core.intake_script(CHAT, (FIX / "scripts" / "short_valid.json")
                       .read_text(encoding="utf-8"))
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate,
                 ws.load_short().content_sha()[:8])
    proof = ws.path / "short_proof.mp4"
    if not proof.exists():
        # A stand-in clip, so the proof step has something to play.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=540x960:rate=30:duration=24", "-f", "lavfi",
                        "-i", "sine=frequency=220:duration=24", "-shortest",
                        "-pix_fmt", "yuv420p", str(proof)], check=True)
    if "none yet" in core.proof_notes(CHAT, []).text:
        core.proof_notes(CHAT, ["add", "0:04", "the", "chart", "lands", "before", "he", "names", "it"])
        core.proof_notes(CHAT, ["add", "0:15", "mouth", "keeps", "moving", "after", "the", "line"])
    # A finished SHORT not uploaded yet, so the calendar offers it a free day.
    core.start_lane(CHAT, "short", "SMPL")
    done = Workspace.latest_for(core.settings, "SMPL").path / "short_final.mp4"
    if not done.exists():
        shutil.copyfile(proof, done)
    # A second video with nothing in it yet, and a LONG waiting on its angle.
    core.start_lane(CHAT, "long", "DEMO")
    core.start_lane(CHAT, "short", "EXMPL")
    seed_pages(core.settings)


def seed_pages(settings: Settings) -> None:
    """Ideas, a watch list, an earnings date and a few uploads (made-up
    ones), so the Ideas and Calendar screens have something to show."""
    queue = IdeaQueue(settings)
    if not queue.ranked(limit=1):
        queue.add("DEMO", "down 40% from the high on a guidance cut", "screener",
                  score=2.6, lane="long")
        queue.add("SMPL", "up 11% on volume three times normal", "screener",
                  score=3.1, lane="short")
        queue.add("TEST", "the thesis from March moved", "thesis", score=2.0)
        Watchlist(settings).add("SMPL")
        today = date.today()
        EarningsCalendar(settings).set("SMPL", (today + timedelta(days=6)).isoformat(), "amc")
        log = VideoLog(settings)
        at = lambda d, h: datetime.combine(today + timedelta(days=d), time(h), timezone.utc).isoformat()
        for i, (t, d, fmt, privacy) in enumerate([("SMPL", -9, "short", "public"),
                                                   ("DEMO", -5, "long", "public"),
                                                   ("TEST", -2, "short", "public"),
                                                   ("SMPL", 2, "short", "scheduled")]):
            log.record(VideoRecord(ticker=t, video_id=f"demo{i:07d}", title=f"{t} demo {fmt}",
                                   privacy=privacy, publish_at=at(d, 15), uploaded_at=at(min(d, 0), 9),
                                   workdate=(today + timedelta(days=min(d, -1))).isoformat(), fmt=fmt))


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dennis-panel-demo")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    settings = Settings(MOCK_MODE=True, DATA_STALE_BLOCKS=False,
                        workspace_dir=folder / "workspace", cache_dir=folder / "cache",
                        state_dir=folder / "state", operator_chat_ids=[CHAT],
                        _env_file=None)
    settings.ensure_runtime_dirs()
    core = BotCore(settings)
    core.feed = Feed()
    seed(core)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _server, url = start_panel(core, loop, host="127.0.0.1", port=port)
    print(url, flush=True)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
