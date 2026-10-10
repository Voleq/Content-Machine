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
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import Settings
from pipeline.models import LongScript, ShortScript


# A `YYYY-MM-DD` workspace directory. Compared as a string before it
# is parsed, which is why the format is pinned here.
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today_str() -> str:
    return date.today().isoformat()


def _write(path: Path, text: str) -> None:
    """Write `text` to `path` whole or not at all (temp file, then rename):
    a crash mid-write left a half script or a half approval that every later
    command then failed to parse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return default
    return data if isinstance(data, type(default)) else default


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
    def dates_for(cls, settings: Settings, ticker: str) -> list[str]:
        """This ticker's workspace dates, newest first — date folders only,
        so a stray folder beside them is never taken for the latest."""
        base = settings.workspace_dir / ticker.upper()
        if not base.is_dir():
            return []
        return sorted((d.name for d in base.iterdir()
                       if d.is_dir() and _DATE_DIR_RE.match(d.name)),
                      reverse=True)

    @staticmethod
    def split_arg(arg: str) -> tuple[str, str]:
        """`TICKER` or `TICKER@YYYY-MM-DD` -> (ticker, date or "")."""
        ticker, _, when = (arg or "").strip().partition("@")
        return ticker.strip().upper(), when.strip()

    @classmethod
    def resolve(cls, settings: Settings, arg: str,
                want=None) -> "Workspace | None":
        """The workspace a command about `arg` means (M3).

        `TICKER@YYYY-MM-DD` names one outright. Otherwise the newest date
        folder for which `want(ws)` holds — the one with the script to
        render, the video to upload — and failing that the newest of all.
        Taking the newest unconditionally meant a `/short` started today
        hid yesterday's approved LONG from `/render`, `/upload` and the rest,
        with no way to name the older folder.
        """
        ticker, when = cls.split_arg(arg)
        if not ticker:
            return None
        if when:
            ws = cls(settings, ticker, when)
            return ws if _DATE_DIR_RE.match(when) and ws.exists else None
        dates = cls.dates_for(settings, ticker)
        if want is not None:
            for d in dates:
                ws = cls(settings, ticker, d)
                try:
                    if want(ws):
                        return ws
                except Exception:  # noqa: BLE001 - a bad folder is skipped
                    continue
        return cls(settings, ticker, dates[0]) if dates else None

    @classmethod
    def latest_for(cls, settings: Settings, ticker: str) -> "Workspace | None":
        return cls.resolve(settings, ticker)

    # -------------------------------------------------------------- scripts
    def save_short(self, script: ShortScript, raw: str) -> None:
        self._save_script("short", script, raw)

    def save_long(self, script: LongScript, raw: str) -> None:
        self._save_script("long", script, raw)

    def _save_script(self, fmt: str, script, raw: str) -> None:
        # The same text again (a swap re-intake, "back to report") is not a
        # revision: stacking it made `/undo` step through identical copies.
        if self.raw_script(fmt) != raw:
            self._push_revision(fmt)
        _write(self.path / f"script_{fmt}.raw.txt", raw)
        _write(self.path / f"script_{fmt}.json", script.model_dump_json(indent=2))
        self._invalidate_approval(fmt)

    def raw_script(self, fmt: str) -> str | None:
        f = self.path / f"script_{fmt}.raw.txt"
        return f.read_text(encoding="utf-8") if f.exists() else None

    # ------------------------------------------------------------ lane (1d)
    # `/short` and `/long` declare the format up front instead of preparing
    # both prompts and leaving it implicit, so /render follows from the lane
    # rather than being a second, separate choice.
    def _lane_file(self) -> Path:
        return self.path / "lane.json"

    def set_lane(self, lane: str, *, update: bool = False) -> None:
        _write(self._lane_file(),
               json.dumps({"lane": lane, "update": bool(update)}))

    def _lane_data(self) -> dict:
        try:
            data = json.loads(self._lane_file().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def lane(self) -> str:
        return str(self._lane_data().get("lane") or "")

    def is_update(self) -> bool:
        """Whether this workspace is Dennis revisiting his own call.

        Deliberately NOT a third lane. An update is a LONG in every mechanical
        sense — same parser, same renderer, same validation — and making it a
        lane would put an unknown value in front of `current_format()`, which
        every render path reads. It is a flag on the long lane, which is what
        it actually is: one prompt swapped, nothing else.
        """
        return bool(self._lane_data().get("update"))

    def current_format(self) -> str | None:
        """Which format this workspace is working in: the declared lane.

        It used to be inferred from which files existed on disk, LONG
        unconditionally winning — which is backwards, and is why one stray
        paste poisoned a ticker for the day (C3). Approve the real SHORT and
        the bot told you to type `/render`, which then reported that the LONG
        was not approved; tap Approve on a junk LONG report and it rendered
        16:9 with the paid voice reading JSON fragments.

        The lane is declared once, by `/short` or `/long`, and never
        inferred. A script file that disagrees with it is a bug to refuse
        (see `format_conflict`), not a signal to follow.

        `None` only for a workspace with no lane at all — an old folder, or
        one created before the lane existed.
        """
        return self.lane() or None

    def format_conflict(self) -> str | None:
        """A script on file for a format this workspace is not in, if any.

        Returns the offending format's name. The caller decides what to say;
        what matters here is that the disagreement is VISIBLE rather than
        silently resolved in favour of whichever file happens to exist.
        """
        lane = self.lane()
        if not lane:
            return None
        other = "short" if lane == "long" else "long"
        if (self.path / f"script_{other}.json").exists():
            return other
        return None

    # ------------------------------------------------------- revisions (P3.1c)
    # In-chat editing needs an undo. Every save stacks the previous raw here
    # first, so a revision that parses but reads badly is one command away
    # from being reverted — and one that does NOT parse never lands at all
    # (the caller validates before saving).
    def _revision_dir(self, fmt: str) -> Path:
        return self.path / "revisions" / fmt

    def _revisions(self, fmt: str) -> list[Path]:
        """The stack, oldest first — in NUMBER order. Sorted as strings,
        `1000.txt` came before `999.txt` and `/undo` took the wrong one."""
        d = self._revision_dir(fmt)
        if not d.is_dir():
            return []
        return sorted((p for p in d.glob("*.txt") if p.stem.isdigit()),
                      key=lambda p: int(p.stem))

    def _next_revision(self, fmt: str) -> Path:
        d = self._revision_dir(fmt)
        d.mkdir(parents=True, exist_ok=True)
        have = self._revisions(fmt)
        n = int(have[-1].stem) + 1 if have else 0
        return d / f"{n:03d}.txt"

    def _push_revision(self, fmt: str) -> None:
        current = self.path / f"script_{fmt}.raw.txt"
        if not current.exists():
            return
        _write(self._next_revision(fmt), current.read_text(encoding="utf-8"))

    def revision_count(self, fmt: str) -> int:
        return len(self._revisions(fmt))

    def pop_revision(self, fmt: str) -> str | None:
        """The previous raw script, removed from the stack. None if empty."""
        files = self._revisions(fmt)
        if not files:
            return None
        last = files[-1]
        text = last.read_text(encoding="utf-8")
        last.unlink()
        return text

    def push_revision_text(self, fmt: str, text: str) -> None:
        """Put a popped revision back (G1).

        `/undo` pops, then asks the caller to save, then pops again to drop
        what the save pushed. When the save is REFUSED nothing was pushed, so
        the undo has to put back what it took or a rejected revert silently
        costs a revision.
        """
        _write(self._next_revision(fmt), text)

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
        _write(self._angle_file(), json.dumps({"awaiting": True, "chosen": ""}))

    def set_chosen_angle(self, text: str) -> None:
        _write(self._angle_file(), json.dumps(
            {"awaiting": False, "chosen": text.strip()}, indent=2))

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
            _write(self._angle_file(), json.dumps(st, indent=2))

    def chosen_angle(self) -> str:
        return self._angle_state().get("chosen", "")

    # ------------------------------------------------- headline short (/headline)
    # A headline-driven SHORT: the operator supplied a specific news item (not a
    # screener mover). The stored state carries the detected mode (company /
    # earnings / macro), the headline text, and an optional fetched summary.
    def _headline_file(self) -> Path:
        return self.path / "headline.json"

    def set_headline(self, payload: dict) -> None:
        _write(self._headline_file(), json.dumps(payload, indent=2))

    def headline(self) -> dict:
        f = self._headline_file()
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------ the operator's own words
    #
    # WHY THIS ONE, IN THE OPERATOR'S WORDS (03). The thesis exists inside the
    # angle prompt and evaporates when the prompt is answered; nothing on disk
    # ever held the human judgement behind a video. YouTube's originality rule
    # asks for exactly that judgement, and a pipeline that renders one template
    # per ticker has to be able to point at it.
    #
    # Captured at intake, printed above Approve, and carried into the
    # description, so it is one sentence written once and used three times.

    def _why_file(self) -> Path:
        return self.path / "why.txt"

    def set_why(self, text: str) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._why_file().write_text(text.strip() + "\n", encoding="utf-8")

    @property
    def why(self) -> str:
        f = self._why_file()
        try:
            return f.read_text(encoding="utf-8").strip() if f.exists() else ""
        except OSError:
            return ""

    # ------------------------------------------------------------- approval
    def _approval_file(self, fmt: str) -> Path:
        return self.path / f"approval_{fmt}.json"

    def approve(self, fmt: str, script_sha: str, report_text: str) -> None:
        _write(self._approval_file(fmt), json.dumps({
            "script_sha": script_sha,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "report": report_text,
        }, indent=2))

    def approved_sha(self, fmt: str) -> str | None:
        """The approved sha, or None — an unreadable approval is none: the
        safe reading of a spend gate, and not a crash in `/render`."""
        return _read_json(self._approval_file(fmt), {}).get("script_sha")

    def is_approved(self, fmt: str) -> bool:
        """True only if the CURRENT script content matches the approval."""
        sha = self.approved_sha(fmt)
        if sha is None:
            return False
        try:
            script = self.load_short() if fmt == "short" else self.load_long()
        except ValueError:  # a script the current schema no longer reads
            return False
        return script is not None and script.content_sha() == sha

    def _invalidate_approval(self, fmt: str) -> None:
        self._approval_file(fmt).unlink(missing_ok=True)

    # ------------------------------------------------------ b-roll overrides
    def broll_overrides(self) -> dict[str, int]:
        return _read_json(self.path / "broll_overrides.json", {})

    def set_broll_override(self, key: str, choice: int) -> dict[str, int]:
        overrides = self.broll_overrides()
        overrides[key] = choice
        _write(self.path / "broll_overrides.json", json.dumps(overrides, indent=2))
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
        _write(self.path, json.dumps(data, indent=2))

    def get(self, chat_id: int) -> Workspace | None:
        entry = self._load().get(str(chat_id))
        if not entry:
            return None
        ws = Workspace(self.settings, entry["ticker"], entry["workdate"])
        return ws if ws.exists else None


def audited_tickers_since(settings: Settings, days: int) -> set[str]:
    """Tickers with a workspace newer than `days` — the screener cooldown.

    Reads the DATE DIRECTORY NAMES and stops at the first one inside the
    window (J5). It used to walk every date directory of every ticker on
    every screen, which is fine at today's volume and grows without bound
    alongside the thesis book: a year of daily videos is 365 directories per
    ticker, and the screener runs this on every candidate.

    Two cheap changes rather than an index, because an index is a second
    thing to keep true: the ticker directories are sorted so the newest
    dates come first and the scan stops as soon as one qualifies, and the
    cutoff is compared as a DATE STRING, so the parse only happens for the
    handful of names that could matter.
    """
    out: set[str] = set()
    root = settings.workspace_dir
    if not root.is_dir():
        return out
    # LOCAL, because the names being compared are local. Every directory
    # here is named by `today_str()`, which is `date.today()` — the
    # operator's own day — and the cutoff was built from `utcnow()`. West of
    # UTC the two disagree for most of the day, so the cooldown ran a day
    # long or a day short depending on the hour, and the string comparison
    # below hid it by never parsing either side.
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    for tdir in root.iterdir():
        if not tdir.is_dir() or tdir.name.startswith("_"):
            continue
        # Newest first: the answer is almost always the first name.
        for name in sorted((d.name for d in tdir.iterdir() if d.is_dir()),
                           reverse=True):
            if name < cutoff:
                break          # every remaining name is older still
            if _DATE_DIR_RE.match(name):
                out.add(tdir.name)
                break
    return out
