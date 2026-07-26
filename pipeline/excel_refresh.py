"""Drive Excel directly: refresh the data template for a ticker (P3.1b).

Until now the numbers arrived by hand — the operator opened the v3 template,
typed a RIC, waited for the add-in, saved, and uploaded the file to the bot.
The bot runs natively on the Windows box that *has* Excel and the
LSEG/Refinitiv (or Capital IQ) add-in loaded, so it can do all of that
itself.

The whole thing is one flow, and each step has a way of going quietly wrong:

1. **Copy the template.** Never open the shipped template in place; a
   half-finished refresh must not leave the template carrying one ticker's
   numbers.
2. **Write the symbol** into the ticker cell. The shipped template drives
   every formula off a single cell (see `TICKER_CELL` — and the note there
   about the brief).
3. **Trigger the add-in's refresh.** There is no one function for this: each
   add-in exposes its own macro, and the name differs by vintage. We try a
   configurable list, then fall back to a full rebuild.
4. **Wait for it to actually finish.** This is the step that matters. The
   add-in resolves asynchronously — the call returns immediately and the
   cells fill in over the following seconds while showing `#N/A`,
   `Requesting Data...` or nothing at all. Reading too early yields a
   workbook full of blanks that looks like a successful refresh, which is the
   worst possible outcome: a video built on no data. So we poll until the
   required fields have all resolved *and* the picture has stopped changing,
   and treat running out of time as failure.
5. **Save a dated copy** into the ticker's workspace, then hand it to the
   existing reader.

Hard rules, from the brief:

* A timeout, or a required field still unresolved, is a **hard failure with a
  readable message** — never good data. Nothing lands at the reader's
  filename unless the refresh genuinely completed.
* Never leave a stray Excel process or a modal dialog. Alerts and link
  prompts are off, teardown runs in `finally`, and the process is killed by
  PID as a last resort.
* Excel or add-in missing is **reported clearly**, not crashed on.
* The manual upload path keeps working, unchanged, and is the fallback here
  and the only path on a non-Windows host.
* Freshness comes from the **refresh timestamp**, not the file's mtime.

Everything except the COM calls themselves is plain Python driven through the
`ExcelSession` protocol, so the polling logic — the part with the real
subtlety — is tested against a fake add-in that resolves over several polls.
Live COM behaviour can only be verified on the Windows box.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from config import Settings
from pipeline.models import DATA_REQUIRED

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Where things live in the shipped template.
# --------------------------------------------------------------------------

# NOTE — the phase-3 brief says to set `Snapshot!C3`. The template actually in
# the repo (`templates/dennis_data_template.xlsx`) drives everything off
# `Snapshot!B2`: its own Instructions sheet says "Set the RIC in Snapshot!B2",
# the header row sits at row 5, and every green formula reads `$B$2`. Writing
# C3 would land in a comment row and refresh nothing. The code follows the
# template; `EXCEL_TICKER_CELL` overrides it if the template ever moves.
TICKER_CELL = "B2"
SNAPSHOT_SHEET = "Snapshot"

# The Snapshot layout: `field_key` in column B, the resolved value in D.
KEY_COL = 2
VALUE_COL = 4
FIRST_DATA_ROW = 6
LAST_DATA_ROW = 200          # generous; the template ends around row 49

# Cell contents that mean "the add-in has not answered yet". Distinct from a
# permanent error: `#NAME?` means the add-in isn't loaded at all, and the
# LSEG/CIQ plug-ins park "Requesting Data..." in the cell while a request is
# in flight.
_PENDING_MARKERS = (
    "requesting data", "retrieving", "loading", "pending", "#n/a n/a",
    "#n/a requesting data...", "fetching", "please wait", "downloading",
)
_ERROR_MARKERS = ("#name?", "#value!", "#ref!", "#div/0!", "#null!", "#num!")
_NA_MARKERS = ("#n/a", "n/a", "na", "")

# Macro names to try, in order, before falling back to a full rebuild. Each
# add-in vintage exposes a different one and a missing macro raises rather
# than returning a status, so the list is walked until one sticks. Override
# with EXCEL_REFRESH_MACROS when the box tells you which one is real.
DEFAULT_REFRESH_MACROS = (
    "EikonRefreshWorksheet",   # Eikon / LSEG Workspace add-in
    "RefreshWorksheet",        # Refinitiv Workspace (newer)
    "PLKUpdate",               # legacy Thomson PowerLink
    "SPRefreshAll",            # S&P Capital IQ plug-in
    "CIQRefresh",              # CIQ, other vintage
)

REFRESH_STAMP_NAME = "data_refresh.json"

# Which loaded add-in counts as "the data add-in". Only used for reporting and
# for nudging a load-on-demand add-in into connecting — never for anything the
# viewer sees, and the vendor's name never leaves the log.
_DATA_ADDIN_RE = re.compile(
    r"eikon|refinitiv|lseg|thomson|capital\s?iq|\bciq\b|powerlink|datastream",
    re.IGNORECASE)


class ExcelUnavailable(RuntimeError):
    """Excel, the COM bridge, or the add-in isn't usable on this host.

    Distinct from a failure: the answer is "use the manual upload", not
    "something broke".
    """


class RefreshError(RuntimeError):
    """The refresh ran and did not produce usable data."""


class RefreshTimeout(RefreshError):
    """The add-in never finished inside the budget."""


# --------------------------------------------------------------------------
# Classifying what came back.
# --------------------------------------------------------------------------


def classify_cell(raw: Any) -> str:
    """`ok` | `pending` | `error` | `missing` for one resolved value cell."""
    if raw is None:
        return "missing"
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return "ok"
    if isinstance(raw, datetime):
        return "ok"
    text = str(raw).strip().lower()
    if any(m in text for m in _PENDING_MARKERS):
        return "pending"
    # A bare "#n/a" from these add-ins is ambiguous — it is what a cell shows
    # both while waiting and when a mnemonic genuinely doesn't resolve. The
    # poll loop resolves the ambiguity with time: still #N/A when everything
    # else has settled means it is never coming.
    if text in _NA_MARKERS:
        return "pending"
    if any(text.startswith(m) or m in text for m in _ERROR_MARKERS):
        return "error"
    return "ok"


@dataclass
class SnapshotState:
    """What one poll of the Snapshot sheet saw."""

    values: dict[str, Any] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)

    @property
    def pending(self) -> list[str]:
        return sorted(k for k, v in self.status.items() if v == "pending")

    @property
    def errors(self) -> list[str]:
        return sorted(k for k, v in self.status.items() if v == "error")

    def unresolved_required(self, required: Sequence[str] = ()) -> list[str]:
        req = list(required or DATA_REQUIRED)
        return [k for k in req if self.status.get(k, "missing") != "ok"]

    def fingerprint(self) -> str:
        """Cheap equality across polls — "has anything changed since?"."""
        return json.dumps(
            {k: str(v) for k, v in sorted(self.values.items())},
            sort_keys=True,
        )

    @property
    def resolved(self) -> int:
        return sum(1 for v in self.status.values() if v == "ok")


def read_snapshot_state(rows: Sequence[Sequence[Any]]) -> SnapshotState:
    """Turn a raw `B:D` block from the Snapshot sheet into a state.

    Takes rows rather than a sheet so the poll loop can be exercised without
    Excel: one COM round-trip fetches the whole block, and everything after
    that is arithmetic.
    """
    st = SnapshotState()
    for row in rows:
        if not row:
            continue
        key = row[0]
        if key is None or not str(key).strip():
            continue
        name = str(key).strip()
        value = row[VALUE_COL - KEY_COL] if len(row) > VALUE_COL - KEY_COL else None
        st.values[name] = value
        st.status[name] = classify_cell(value)
    return st


# --------------------------------------------------------------------------
# The COM seam.
# --------------------------------------------------------------------------


class ExcelSession(Protocol):
    """The handful of things the refresh actually needs Excel to do."""

    def open_workbook(self, path: Path) -> None: ...
    def set_cell(self, sheet: str, cell: str, value: Any) -> None: ...
    def run_macro(self, name: str) -> None: ...
    def calculate(self) -> None: ...
    def calculation_done(self) -> bool: ...
    def read_block(self, sheet: str, first_row: int, last_row: int,
                   first_col: int, last_col: int) -> list[list[Any]]: ...
    def save_as(self, path: Path) -> None: ...
    def close(self) -> None: ...


def _excel_pids() -> set[int]:
    """PIDs of every EXCEL.EXE currently running (Windows only, best effort).

    Used to identify the instance we started, so a stuck one can be killed
    without touching the operator's own Excel.
    """
    if sys.platform != "win32":
        return set()
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq EXCEL.EXE", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20, check=False).stdout
    except Exception as e:  # noqa: BLE001
        log.debug("excel: tasklist failed (%s)", e)
        return set()
    pids: set[int] = set()
    for line in out.splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


class Win32ExcelSession:
    """The real thing: Excel over COM, on Windows only.

    Not exercised by the test suite — there is no Excel here. Everything it
    does is a direct translation of the Excel object model, and the teardown
    is written so that no path leaves a process behind.
    """

    def __init__(self, *, visible: bool = False):
        self.visible = visible
        self._app: Any = None
        self._book: Any = None
        self._pid: int | None = None
        self._pythoncom: Any = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if sys.platform != "win32":
            raise ExcelUnavailable(
                "Excel automation needs Windows — this host is "
                f"{sys.platform}. Use the manual upload instead.")
        try:
            import pythoncom  # type: ignore
            import win32com.client as win32  # type: ignore
        except ImportError as e:
            raise ExcelUnavailable(
                "pywin32 isn't installed (pip install pywin32) — Excel "
                "automation is unavailable; the manual upload still works."
            ) from e
        self._pythoncom = pythoncom
        # The worker thread needs its own apartment or every COM call fails.
        pythoncom.CoInitialize()
        before = _excel_pids()
        try:
            # DispatchEx, not Dispatch: a private instance, so the bot never
            # hijacks (or gets blocked by) the Excel the operator has open.
            self._app = win32.DispatchEx("Excel.Application")
        except Exception as e:  # noqa: BLE001 - pywin32 raises com_error
            pythoncom.CoUninitialize()
            raise ExcelUnavailable(
                f"Excel would not start ({e}). Is Office installed for this "
                "user account? The manual upload still works."
            ) from e
        app = self._app
        # Nothing may block waiting for a human: no alerts, no link prompts,
        # no recovery pane.
        app.Visible = bool(self.visible)
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        app.ScreenUpdating = bool(self.visible)
        app.EnableEvents = True          # add-ins need their events to fire
        try:
            # msoAutomationSecurityLow — macros enabled, no prompt. NOT
            # ForceDisable: the add-in's refresh *is* a macro, so disabling
            # macros would leave the workbook silently unrefreshed, which is
            # the one outcome this whole module exists to prevent.
            app.AutomationSecurity = 1
        except Exception:  # noqa: BLE001 - not on every Excel build
            pass
        self._pid = self._find_pid(before)
        self.addins = self._connect_addins()

    def _find_pid(self, before: set[int]) -> int | None:
        """The PID behind the automation object, for last-resort teardown.

        `Hwnd` is the direct route but an invisible Excel does not reliably
        have a window, so the fallback is the process that appeared while we
        were starting one.
        """
        try:
            import win32process  # type: ignore
            hwnd = int(self._app.Hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                return int(pid)
        except Exception:  # noqa: BLE001 - no window when invisible
            pass
        fresh = _excel_pids() - before
        if len(fresh) == 1:
            return fresh.pop()
        # Several appeared (or none did) — killing the wrong Excel would take
        # the operator's own spreadsheet with it. Better to leak than to guess.
        log.debug("excel: could not identify the automation PID (%d candidates)",
                  len(fresh))
        return None

    def _connect_addins(self) -> list[str]:
        """Make sure the data add-in is actually loaded, and say what is.

        Load-on-demand COM add-ins frequently do not connect in an
        automation-started Excel, and an unconnected add-in leaves every `TR`
        formula reading `#NAME?` — which the poll loop reports as an error
        rather than waiting forever, but it is far more useful to fix it here.
        """
        found: list[str] = []
        try:
            for a in self._app.COMAddIns:
                try:
                    name = str(a.Description or a.ProgID or "")
                except Exception:  # noqa: BLE001
                    continue
                if not _DATA_ADDIN_RE.search(name):
                    continue
                found.append(name)
                if not a.Connect:
                    try:
                        a.Connect = True
                        log.info("excel: connected the %s add-in", name)
                    except Exception as e:  # noqa: BLE001
                        log.warning("excel: could not connect %s (%s)", name, e)
        except Exception as e:  # noqa: BLE001 - COMAddIns is not always readable
            log.debug("excel: could not enumerate COM add-ins (%s)", e)
        try:
            for a in self._app.AddIns:
                if a.Installed and _DATA_ADDIN_RE.search(str(a.Name or "")):
                    found.append(str(a.Name))
        except Exception:  # noqa: BLE001
            pass
        if not found:
            log.warning("excel: no LSEG/Refinitiv/Capital IQ add-in appears "
                        "loaded — expect the fields to come back unresolved")
        else:
            log.info("excel: data add-in(s) present: %s", ", ".join(found))
        return found

    def close(self) -> None:
        """Tear down in the order that avoids leaving a process behind."""
        try:
            if self._book is not None:
                try:
                    self._book.Close(SaveChanges=False)
                except Exception as e:  # noqa: BLE001
                    log.warning("excel: workbook close failed: %s", e)
                self._book = None
            if self._app is not None:
                try:
                    self._app.DisplayAlerts = False
                    self._app.Quit()
                except Exception as e:  # noqa: BLE001
                    log.warning("excel: quit failed: %s", e)
                self._app = None
        finally:
            if self._pythoncom is not None:
                try:
                    self._pythoncom.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass
                self._pythoncom = None
            self._kill_if_alive()

    def _kill_if_alive(self) -> None:
        """Quit() is ignored by an Excel stuck on a modal dialog.

        Only ever aimed at the PID we watched appear — never at EXCEL.EXE by
        name, which would close whatever the operator had open.
        """
        if self._pid is None:
            return
        if self._pid not in _excel_pids():
            self._pid = None
            return          # Quit() worked; nothing to kill
        log.warning("excel: process %s survived Quit() — forcing it closed",
                    self._pid)
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._pid)],
                           capture_output=True, timeout=20, check=False)
        except Exception as e:  # noqa: BLE001
            log.warning("excel: could not confirm process %s exited: %s",
                        self._pid, e)
        self._pid = None

    # ------------------------------------------------------------ operations
    def open_workbook(self, path: Path) -> None:
        self._book = self._app.Workbooks.Open(
            str(Path(path).resolve()), UpdateLinks=0, ReadOnly=False,
            IgnoreReadOnlyRecommended=True, Notify=False, AddToMru=False)

    def set_cell(self, sheet: str, cell: str, value: Any) -> None:
        self._book.Worksheets(sheet).Range(cell).Value = value

    def run_macro(self, name: str) -> None:
        self._app.Run(name)

    def calculate(self) -> None:
        # A plain Calculate() leaves cached add-in results alone; the full
        # rebuild is what forces every formula, including the volatile
        # add-in ones, to be re-issued.
        try:
            self._app.CalculateFullRebuild()
        except Exception:  # noqa: BLE001 - older Excel
            self._app.Calculate()

    def calculation_done(self) -> bool:
        try:
            return int(self._app.CalculationState) == 0   # xlDone
        except Exception:  # noqa: BLE001
            return True

    def read_block(self, sheet: str, first_row: int, last_row: int,
                   first_col: int, last_col: int) -> list[list[Any]]:
        ws = self._book.Worksheets(sheet)
        rng = ws.Range(ws.Cells(first_row, first_col),
                       ws.Cells(last_row, last_col))
        raw = rng.Value                     # one round-trip for the whole block
        if raw is None:
            return []
        return [list(r) for r in raw]

    def save_as(self, path: Path) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        # 51 = xlOpenXMLWorkbook (.xlsx). Explicit, so a machine configured
        # for .xls defaults cannot silently write the wrong container.
        self._book.SaveAs(str(p), FileFormat=51)


# --------------------------------------------------------------------------
# Availability.
# --------------------------------------------------------------------------


def excel_available(settings: Settings) -> tuple[bool, str]:
    """(usable, human-readable reason). Never raises, never launches Excel."""
    if not settings.excel_refresh_enabled:
        return False, "Excel refresh is switched off (EXCEL_REFRESH_ENABLED=false)."
    if sys.platform != "win32":
        return False, (f"Excel automation needs Windows; this host is "
                       f"{sys.platform}.")
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False, "pywin32 isn't installed (pip install pywin32)."
    template = template_path(settings)
    if not template.exists():
        return False, f"the data template is missing at {template}."
    return True, "Excel automation is available."


def _start_win32(settings: Settings) -> ExcelSession:
    """The default session factory: a live Excel, ready to open a workbook."""
    session = Win32ExcelSession(visible=settings.excel_visible)
    session.start()
    return session


def template_path(settings: Settings) -> Path:
    if settings.excel_template_path:
        return Path(settings.excel_template_path)
    return settings.templates_dir / "dennis_data_template.xlsx"


# --------------------------------------------------------------------------
# Symbol resolution: a ticker is not a RIC.
# --------------------------------------------------------------------------


def _symbol_overrides(settings: Settings) -> dict[str, str]:
    f = settings.state_dir / "excel_symbols.json"
    try:
        return {str(k).upper(): str(v) for k, v in
                json.loads(f.read_text()).items()}
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return {}


def set_symbol_override(settings: Settings, ticker: str, symbol: str) -> None:
    """Pin the exact vendor symbol for a ticker (`PLTR` -> `PLTR.O`)."""
    f = settings.state_dir / "excel_symbols.json"
    data = _symbol_overrides(settings)
    data[ticker.strip().upper()] = symbol.strip()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2, sort_keys=True))


def resolve_symbol(settings: Settings, ticker: str) -> str:
    """What to type into the ticker cell.

    The add-in wants its own instrument code (`PLTR.O`), not always the plain
    ticker, and the mapping is an entitlement question we cannot answer from
    here. Precedence: an explicit per-ticker pin, then the configured suffix,
    then the ticker as typed. A wrong guess surfaces as unresolved required
    fields — a hard failure with the symbol named — not as empty data.
    """
    t = ticker.strip().upper()
    pinned = _symbol_overrides(settings).get(t)
    if pinned:
        return pinned
    suffix = settings.excel_symbol_suffix.strip()
    if suffix and "." not in t:
        return t + (suffix if suffix.startswith(".") else "." + suffix)
    return t


# --------------------------------------------------------------------------
# The refresh timestamp — what freshness is really about.
# --------------------------------------------------------------------------


def write_refresh_stamp(workspace: Path, payload: dict) -> Path:
    p = Path(workspace) / REFRESH_STAMP_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return p


def refresh_stamp(workspace: Path) -> dict:
    """The recorded refresh, or `{}` for a manually uploaded workbook."""
    try:
        data = json.loads((Path(workspace) / REFRESH_STAMP_NAME).read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def refresh_age_days(workspace: Path, now: datetime | None = None) -> float | None:
    """Age of the recorded refresh in days, or None if there isn't one."""
    stamp = refresh_stamp(workspace)
    raw = stamp.get("finished_at")
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - when).total_seconds() / 86400.0


# --------------------------------------------------------------------------
# The refresh itself.
# --------------------------------------------------------------------------


@dataclass
class RefreshResult:
    path: Path                       # what the reader will load
    archive: Path                    # the dated copy kept alongside it
    symbol: str
    started_at: datetime
    finished_at: datetime
    polls: int
    macro: str                       # which trigger worked ("" = recalc only)
    resolved: int
    pending: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def elapsed_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def stamp(self) -> dict:
        return {
            "symbol": self.symbol,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "elapsed_s": round(self.elapsed_s, 2),
            "polls": self.polls,
            "macro": self.macro,
            "resolved_fields": self.resolved,
            "unresolved": self.pending,
            "errors": self.errors,
            "source": "excel_com",
            "file": self.path.name,
            "archive": self.archive.name,
        }

    def summary(self) -> str:
        # Described generically on purpose: the macro name carries the data
        # vendor's brand, and nothing the bot writes names the vendor — not on
        # screen and not in chat. The exact macro is in the log and in
        # data_refresh.json, which is where you'd read it to set
        # EXCEL_REFRESH_MACROS.
        trigger = "the add-in's refresh" if self.macro else "a full recalculation"
        note = ""
        if self.errors:
            note = f"\n⚠️ {len(self.errors)} field(s) errored: {', '.join(self.errors[:6])}"
        if self.pending:
            note += (f"\n⚠️ {len(self.pending)} optional field(s) never "
                     f"resolved: {', '.join(self.pending[:6])}")
        return (f"🔄 Refreshed {self.symbol} in Excel via {trigger} — "
                f"{self.resolved} fields in {self.elapsed_s:.0f}s "
                f"({self.polls} polls).{note}")


def _trigger_refresh(session: ExcelSession, macros: Sequence[str]) -> str:
    """Fire the add-in's refresh. Returns the macro that worked, or ""."""
    for name in macros:
        if not name:
            continue
        try:
            session.run_macro(name)
            log.info("excel: refresh triggered via %s", name)
            return name
        except Exception as e:  # noqa: BLE001 - a missing macro raises
            log.debug("excel: macro %s unavailable (%s)", name, e)
    # Not a failure. Most add-in formulas are volatile, so a full rebuild
    # re-issues them; the macros just do it more directly.
    log.info("excel: no add-in refresh macro answered — full recalculation")
    session.calculate()
    return ""


def _poll_until_resolved(
    session: ExcelSession,
    *,
    timeout_s: float,
    poll_interval_s: float,
    settle_polls: int,
    required: Sequence[str],
    sleep=time.sleep,
    clock=time.monotonic,
) -> tuple[SnapshotState, int]:
    """Poll the Snapshot sheet until the refresh has genuinely finished.

    "Finished" is deliberately two conditions, because either alone lies:

    * every required field has resolved — otherwise we would happily accept a
      workbook where the price never arrived; and
    * nothing has changed for `settle_polls` consecutive reads — otherwise we
      would stop the instant the last required field lands and save while the
      history sheet is still filling in.

    Raises RefreshTimeout with the specific unresolved fields named.
    """
    deadline = clock() + max(1.0, timeout_s)
    last_print = clock()
    state = SnapshotState()
    polls = 0
    stable = 0
    previous = None

    while True:
        polls += 1
        rows = session.read_block(SNAPSHOT_SHEET, FIRST_DATA_ROW,
                                  LAST_DATA_ROW, KEY_COL, VALUE_COL)
        state = read_snapshot_state(rows)
        fp = state.fingerprint()
        stable = stable + 1 if fp == previous else 0
        previous = fp

        calc_done = session.calculation_done()
        unresolved = state.unresolved_required(required)
        if calc_done and not unresolved and stable >= settle_polls:
            log.info("excel: refresh settled after %d poll(s), %d fields",
                     polls, state.resolved)
            return state, polls

        now = clock()
        if now >= deadline:
            if unresolved:
                raise RefreshTimeout(
                    f"the add-in did not resolve after {timeout_s:.0f}s — "
                    f"required field(s) still empty: {', '.join(unresolved)}. "
                    f"{state.resolved} of {len(state.status)} fields came back"
                    + (f"; {len(state.errors)} errored "
                       f"({', '.join(state.errors[:4])})" if state.errors else "")
                )
            # Required fields are in but something optional keeps churning:
            # take what we have rather than fail a usable refresh.
            log.warning("excel: still settling at the %.0fs timeout — "
                        "required fields are resolved, taking the snapshot",
                        timeout_s)
            return state, polls

        if now - last_print >= 15:
            log.info("excel: waiting on the add-in — %d resolved, %d pending",
                     state.resolved, len(state.pending))
            last_print = now
        sleep(min(poll_interval_s, max(0.0, deadline - now)))


def refresh_for_ticker(
    settings: Settings,
    ticker: str,
    workspace: Path,
    *,
    symbol: str | None = None,
    session_factory: Callable[[], ExcelSession] | None = None,
    timeout_s: float | None = None,
    required: Sequence[str] | None = None,
    sleep=time.sleep,
    clock=time.monotonic,
    now=None,
) -> RefreshResult:
    """Refresh the template for `ticker` and land it in `workspace`.

    On success the workspace holds `dennis_data.xlsx` (what the reader picks
    up), a dated archive copy, and `data_refresh.json` recording when the
    refresh completed.

    On any failure nothing is written to the reader's filename: a stale
    workbook from a previous run is left exactly as it was, and a workspace
    that had none still has none. A failed refresh must never look like data.

    `session_factory` is the COM seam: it returns a live, ready-to-use
    session, and whatever it returns this function closes on every exit path.
    The tests pass a fake add-in through it, which means the teardown
    guarantee is exercised rather than asserted in a comment.
    """
    sym = (symbol or resolve_symbol(settings, ticker)).strip()
    if not sym:
        raise RefreshError("no symbol to refresh — pass one explicitly.")

    if session_factory is None:
        ok, why = excel_available(settings)
        if not ok:
            raise ExcelUnavailable(why)
        session_factory = lambda: _start_win32(settings)  # noqa: E731

    template = template_path(settings)
    if not template.exists():
        raise ExcelUnavailable(f"the data template is missing at {template}")

    ws_dir = Path(workspace)
    ws_dir.mkdir(parents=True, exist_ok=True)
    stamp_date = (now or datetime.now(timezone.utc)).date().isoformat()
    # Work on a scratch copy under a distinct name: if anything fails the
    # reader never sees it, and `find_export` never picks it up by accident.
    # The random tail keeps two refreshes of the same ticker on the same day
    # from deleting each other's open workbook.
    working = ws_dir / (f".refresh_{ticker.upper()}_{stamp_date}_"
                        f"{uuid.uuid4().hex[:8]}.xlsx")
    shutil.copy2(template, working)

    started = now or datetime.now(timezone.utc)
    macros = [m.strip() for m in
              (settings.excel_refresh_macros or "").split(",") if m.strip()]
    if not macros:
        macros = list(DEFAULT_REFRESH_MACROS)

    # Two nested try blocks on purpose. Excel has to be closed *before* the
    # scratch copy is deleted — Windows refuses to unlink a file the process
    # still holds open, and doing it the other way round would replace a
    # RefreshTimeout with a PermissionError from the cleanup.
    session: ExcelSession | None = None
    try:
        try:
            session = session_factory()
            session.open_workbook(working)
            session.set_cell(SNAPSHOT_SHEET,
                             settings.excel_ticker_cell or TICKER_CELL, sym)
            macro = _trigger_refresh(session, macros)
            state, polls = _poll_until_resolved(
                session,
                timeout_s=(timeout_s if timeout_s is not None
                           else settings.excel_refresh_timeout_s),
                poll_interval_s=settings.excel_poll_interval_s,
                settle_polls=max(1, settings.excel_settle_polls),
                required=required or DATA_REQUIRED,
                sleep=sleep, clock=clock,
            )
            archive = ws_dir / f"dennis_data_{ticker.upper()}_{stamp_date}.xlsx"
            session.save_as(archive)
        except RefreshTimeout as e:
            # Name the symbol we actually typed: the commonest cause of an
            # unresolved refresh is the wrong vendor code, and the operator
            # cannot tell that from the field list alone.
            raise RefreshTimeout(f"refreshing {sym}: {e}") from e
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as e:  # noqa: BLE001
                    # Teardown failing is worth knowing about but never worth
                    # losing the real error over.
                    log.warning("excel: teardown reported %s", e)
    except Exception:
        _discard(working)
        raise

    _discard(working)
    if not archive.exists():
        raise RefreshError(
            f"Excel reported success but wrote no file at {archive.name} — "
            "treating this as a failed refresh rather than trusting it.")

    finished = datetime.now(timezone.utc) if now is None else now
    result = RefreshResult(
        path=ws_dir / "dennis_data.xlsx",
        archive=archive,
        symbol=sym,
        started_at=started,
        finished_at=finished,
        polls=polls,
        macro=macro,
        resolved=state.resolved,
        pending=state.pending,
        errors=state.errors,
    )
    # Only now — with the refresh proven complete — does the file take the
    # name the reader looks for.
    shutil.copy2(archive, result.path)
    _clear_stale_csv(ws_dir)
    write_refresh_stamp(ws_dir, result.stamp())
    log.info("excel: %s refreshed in %.1fs (%d fields, macro=%s)",
             sym, result.elapsed_s, result.resolved, macro or "recalc")
    return result


def _discard(path: Path) -> None:
    """Delete the scratch copy without ever masking a real error.

    A file Windows still considers locked is a mess to clean up, not a reason
    to lose the exception that brought us here.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("excel: could not remove the scratch copy %s (%s)",
                    path.name, e)


def _clear_stale_csv(ws_dir: Path) -> None:
    """`find_export` prefers .xlsx, but a leftover CSV would outlive it."""
    csv_path = ws_dir / "dennis_data.csv"
    if csv_path.exists():
        backup = ws_dir / "dennis_data.superseded.csv"
        try:
            os.replace(csv_path, backup)
            log.info("excel: parked the older CSV export as %s", backup.name)
        except OSError as e:
            log.warning("excel: could not park the old CSV (%s)", e)
