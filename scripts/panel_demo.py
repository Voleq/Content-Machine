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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.feed import Feed  # noqa: E402
from bot.handlers import BotCore  # noqa: E402
from bot.panel import start_panel  # noqa: E402
from config import Settings  # noqa: E402
from pipeline.workspace import Workspace  # noqa: E402

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
    # A second video with nothing in it yet, and a LONG waiting on its angle.
    core.start_lane(CHAT, "long", "DEMO")
    core.start_lane(CHAT, "short", "EXMPL")


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
