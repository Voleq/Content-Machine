"""Workspace + approval state (§9).

Layout: workspace/<TICKER>/<YYYY-MM-DD>/ holds everything for one video:
the company-data export, screenshots, validated scripts, approval
records, renders and manifests. The bot's "active context" (which
ticker/date a pasted script belongs to) and the coverage history used
for screener cooldowns also live here.

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
        self._push_revision("short")
        (self.path / "script_short.raw.txt").write_text(raw, encoding="utf-8")
        (self.path / "script_short.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
        self._invalidate_approval("short")

    def save_long(self, script: LongScript, raw: str) -> None:
        self._push_revision("long")
        (self.path / "script_long.raw.txt").write_text(raw, encoding="utf-8")
        (self.path / "script_long.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
        self._invalidate_approval("long")

    def raw_script(self, fmt: str) -> str | None:
        f = self.path / f"script_{fmt}.raw.txt"
        return f.read_text(encoding="utf-8") if f.exists() else None

    # ------------------------------------------------------------ lane (1d)
    # `/short` and `/long` declare the format up front instead of preparing
    # both prompts and leaving it implicit, so /render follows from the lane
    # rather than being a second, separate choice.
    def _lane_file(self) -> Path:
        return self.path / "lane.json"

    def set_lane(self, lane: str) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._lane_file().write_text(json.dumps({"lane": lane}), encoding="utf-8")

    def lane(self) -> str:
        try:
            return str(json.loads(self._lane_file().read_text(encoding="utf-8")).get("lane") or "")
        except (FileNotFoundError, json.JSONDecodeError):
            return ""

    def current_format(self) -> str | None:
        """Which format this workspace is working in.

        A pasted script is the strongest signal, then the declared lane. LONG
        wins a tie between two scripts: a workspace holding both is one where a
        SHORT was cut from the LONG, and the LONG is the thing being edited.
        """
        if (self.path / "script_long.json").exists():
            return "long"
        if (self.path / "script_short.json").exists():
            return "short"
        return self.lane() or None

    # ------------------------------------------------------- revisions (P3.1c)
    # In-chat editing needs an undo. Every save stacks the previous raw here
    # first, so a revision that parses but reads badly is one command away
    # from being reverted — and one that does NOT parse never lands at all
    # (the caller validates before saving).
    def _revision_dir(self, fmt: str) -> Path:
        return self.path / "revisions" / fmt

    def _push_revision(self, fmt: str) -> None:
        current = self.path / f"script_{fmt}.raw.txt"
        if not current.exists():
            return
        d = self._revision_dir(fmt)
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.txt")))
        (d / f"{n:03d}.txt").write_text(current.read_text(encoding="utf-8"), encoding="utf-8")

    def revision_count(self, fmt: str) -> int:
        d = self._revision_dir(fmt)
        return len(list(d.glob("*.txt"))) if d.is_dir() else 0

    def pop_revision(self, fmt: str) -> str | None:
        """The previous raw script, removed from the stack. None if empty."""
        d = self._revision_dir(fmt)
        if not d.is_dir():
            return None
        files = sorted(d.glob("*.txt"))
        if not files:
            return None
        last = files[-1]
        text = last.read_text(encoding="utf-8")
        last.unlink()
        return text

    def load_short(self) -> ShortScript | None:
        f = self.path / "script_short.json"
        return ShortScript.model_validate_json(f.read_text(encoding="utf-8")) if f.exists() else None

    def load_long(self) -> LongScript | None:
        f = self.path / "script_long.json"
        return LongScript.model_validate_json(f.read_text(encoding="utf-8")) if f.exists() else None

    # ------------------------------------------------- LONG two-step angle
    # The human decision moved to the ANGLE: after the data upload the bot
    # sends the Step-1 angle prompt and marks the workspace "awaiting angle";
    # the operator's plain-text reply is stored as the chosen angle and used
    # to fill the Step-2 writing prompt.
    def _angle_file(self) -> Path:
        return self.path / "long_angle.json"

    def set_awaiting_angle(self) -> None:
        self._angle_file().write_text(json.dumps({"awaiting": True, "chosen": ""}), encoding="utf-8")

    def set_chosen_angle(self, text: str) -> None:
        self._angle_file().write_text(json.dumps(
            {"awaiting": False, "chosen": text.strip()}, indent=2), encoding="utf-8")

    def _angle_state(self) -> dict:
        f = self._angle_file()
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            return {}

    def awaiting_angle(self) -> bool:
        return bool(self._angle_state().get("awaiting"))

    def clear_awaiting_angle(self) -> None:
        st = self._angle_state()
        if st.get("awaiting"):
            st["awaiting"] = False
            self._angle_file().write_text(json.dumps(st, indent=2), encoding="utf-8")

    def chosen_angle(self) -> str:
        return self._angle_state().get("chosen", "")

    # ------------------------------------------------- headline short (/headline)
    # A headline-driven SHORT: the operator supplied a specific news item (not a
    # screener mover). The stored state carries the detected mode (company /
    # earnings / macro), the headline text, and an optional fetched summary.
    def _headline_file(self) -> Path:
        return self.path / "headline.json"

    def set_headline(self, payload: dict) -> None:
        self._headline_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def headline(self) -> dict:
        f = self._headline_file()
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------- approval
    def _approval_file(self, fmt: str) -> Path:
        return self.path / f"approval_{fmt}.json"

    def approve(self, fmt: str, script_sha: str, report_text: str) -> None:
        self._approval_file(fmt).write_text(json.dumps({
            "script_sha": script_sha,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "report": report_text,
        }, indent=2), encoding="utf-8")

    def approved_sha(self, fmt: str) -> str | None:
        f = self._approval_file(fmt)
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8")).get("script_sha")

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
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def set_broll_override(self, key: str, choice: int) -> dict[str, int]:
        overrides = self.broll_overrides()
        overrides[key] = choice
        (self.path / "broll_overrides.json").write_text(json.dumps(overrides, indent=2), encoding="utf-8")
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
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def set(self, chat_id: int, ticker: str, workdate: str) -> None:
        data = self._load()
        data[str(chat_id)] = {"ticker": ticker.upper(), "workdate": workdate}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
