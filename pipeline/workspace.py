"""Workspace + approval state (§9).

Layout: workspace/<TICKER>/<YYYY-MM-DD>/ holds everything for one audit:
the Refinitiv export, screenshots, validated scripts, approval records,
renders and manifests. The bot's "active context" (which ticker/date a
pasted script belongs to) and the audit history used for screener
cooldowns also live here.

Approval records pin the exact script content hash (sha) — any script
change invalidates the approval, so the render gate can never run on
content the operator did not see (§2.3, §8.3).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from config import Settings
from pipeline.models import LongScript, ShortScript


def today_str() -> str:
    return date.today().isoformat()


class Workspace:
    """One ticker/date working directory."""

    def __init__(self, settings: Settings, ticker: str, workdate: str):
        self.settings = settings
        self.ticker = ticker.upper()
        self.workdate = workdate
        self.path = settings.workspace_dir / self.ticker / workdate

    # ------------------------------------------------------------ lifecycle
    def create(self) -> "Workspace":
        self.path.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    @classmethod
    def latest_for(cls, settings: Settings, ticker: str) -> "Workspace | None":
        base = settings.workspace_dir / ticker.upper()
        if not base.is_dir():
            return None
        dates = sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)
        return cls(settings, ticker, dates[0]) if dates else None

    # -------------------------------------------------------------- scripts
    def save_short(self, script: ShortScript, raw: str) -> None:
        (self.path / "script_short.raw.txt").write_text(raw)
        (self.path / "script_short.json").write_text(script.model_dump_json(indent=2))
        self._invalidate_approval("short")

    def save_long(self, script: LongScript, raw: str) -> None:
        (self.path / "script_long.raw.txt").write_text(raw)
        (self.path / "script_long.json").write_text(script.model_dump_json(indent=2))
        self._invalidate_approval("long")

    def load_short(self) -> ShortScript | None:
        f = self.path / "script_short.json"
        return ShortScript.model_validate_json(f.read_text()) if f.exists() else None

    def load_long(self) -> LongScript | None:
        f = self.path / "script_long.json"
        return LongScript.model_validate_json(f.read_text()) if f.exists() else None

    # ------------------------------------------------------------- approval
    def _approval_file(self, fmt: str) -> Path:
        return self.path / f"approval_{fmt}.json"

    def approve(self, fmt: str, script_sha: str, report_text: str) -> None:
        self._approval_file(fmt).write_text(json.dumps({
            "script_sha": script_sha,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "report": report_text,
        }, indent=2))

    def approved_sha(self, fmt: str) -> str | None:
        f = self._approval_file(fmt)
        if not f.exists():
            return None
        return json.loads(f.read_text()).get("script_sha")

    def is_approved(self, fmt: str) -> bool:
        """True only if the CURRENT script content matches the approval."""
        sha = self.approved_sha(fmt)
        if sha is None:
            return False
        script = self.load_short() if fmt == "short" else self.load_long()
        return script is not None and script.content_sha() == sha

    def _invalidate_approval(self, fmt: str) -> None:
        self._approval_file(fmt).unlink(missing_ok=True)

    # ------------------------------------------------------ b-roll overrides
    def broll_overrides(self) -> dict[str, int]:
        f = self.path / "broll_overrides.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def set_broll_override(self, key: str, choice: int) -> dict[str, int]:
        overrides = self.broll_overrides()
        overrides[key] = choice
        (self.path / "broll_overrides.json").write_text(json.dumps(overrides, indent=2))
        self._invalidate_approval("long")  # picks changed => re-approve
        return overrides


# ---------------------------------------------------------------------------
# Active chat context + audit history.
# ---------------------------------------------------------------------------


class ActiveContext:
    """Which workspace a chat's pasted scripts/uploads belong to."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / "active_context.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def set(self, chat_id: int, ticker: str, workdate: str) -> None:
        data = self._load()
        data[str(chat_id)] = {"ticker": ticker.upper(), "workdate": workdate}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def get(self, chat_id: int) -> Workspace | None:
        entry = self._load().get(str(chat_id))
        if not entry:
            return None
        ws = Workspace(self.settings, entry["ticker"], entry["workdate"])
        return ws if ws.exists else None


def audited_tickers_since(settings: Settings, days: int) -> set[str]:
    """Tickers with a workspace newer than `days` — the screener cooldown."""
    out: set[str] = set()
    root = settings.workspace_dir
    if not root.is_dir():
        return out
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    for tdir in root.iterdir():
        if not tdir.is_dir():
            continue
        for ddir in tdir.iterdir():
            try:
                d = datetime.fromisoformat(ddir.name).replace(tzinfo=timezone.utc)
                if d.timestamp() >= cutoff:
                    out.add(tdir.name)
                    break
            except ValueError:
                continue
    return out
