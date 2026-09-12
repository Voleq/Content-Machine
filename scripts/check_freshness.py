#!/usr/bin/env python3
"""What does the freshness gate make of your real workbook? (P5)

`DATA_STALE_BLOCKS` defaults to true, and a date the gate cannot READ blocks
too — an unreadable date is not evidence of freshness. That is the right
default and it has a sharp edge: the parser handles ISO, US-first, day-first,
`3-Sep-2026`, `Sep 3, 2026` and a raw Excel serial, but the operator's sheet
carries whatever Capital IQ wrote under their locale, and that is unknown
until it is read. A misread date walls you off from your own pipeline with a
message about staleness that is really a message about parsing.

So: read the real file, print the raw cell, print what the parser made of it,
and print the gate's verdict.

    python scripts/check_freshness.py EXMPL 2026-09-12
    python scripts/check_freshness.py EXMPL            # today's workspace
    python scripts/check_freshness.py path/to/dennis_data.xlsx

Exit 0 when the gate would let a render proceed, 1 when it would block. No
network.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _usage() -> int:
    print(__doc__, file=sys.stderr)
    return 2


def _resolve(settings, args: list[str]) -> Path | None:
    """A workbook path, or a TICKER [DATE] pair against the workspace."""
    if not args:
        return None
    first = Path(args[0])
    if first.suffix.lower() in (".xlsx", ".csv") or first.is_file():
        return first if first.is_file() else None

    from pipeline.workspace import Workspace

    ticker = args[0].upper()
    if len(args) > 1:
        ws = Workspace(settings, ticker, args[1])
    else:
        ws = Workspace.latest_for(settings, ticker)
        if ws is None:
            print(f"No workspace for {ticker} under {settings.workspace_dir}",
                  file=sys.stderr)
            return None
    from pipeline.company_data import find_export

    return find_export(ws.path)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _usage()

    from config import get_settings
    from pipeline.company_data import load_company_data
    from pipeline.gates import _AS_OF_FORMATS, _parse_as_of, check_freshness

    settings = get_settings()
    src = _resolve(settings, argv)
    if src is None:
        print("No workbook found. Give a path, or TICKER [DATE].",
              file=sys.stderr)
        return 2

    print(f"workbook      : {src}")
    try:
        data = load_company_data(src.parent)
    except Exception as e:  # noqa: BLE001 — this script IS the diagnostic
        print(f"\nUNREADABLE — {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    raw = data.get("as_of_date")
    print(f"as_of_date    : {raw!r}   (type {type(raw).__name__})")
    parsed = _parse_as_of(str(raw) if raw is not None else "")
    if parsed is None:
        print("parsed as     : NOTHING — the gate cannot read this value")
    else:
        age = (date.today() - parsed).days
        print(f"parsed as     : {parsed.isoformat()}  ({age} day(s) old)")
    print(f"max age       : {settings.data_max_age_days} days")
    print(f"blocking mode : DATA_STALE_BLOCKS={settings.data_stale_blocks}")

    findings = check_freshness(str(raw or ""), settings)
    blocking = [f for f in findings if f.severity == "block"]
    for f in findings:
        print(f"\n  [{f.severity}] {f.message}")

    if not blocking:
        print("\nPASS — the freshness gate would let this render proceed."
              + ("" if findings else " Nothing to report at all."))
        return 0

    print("\nBLOCKED — this workbook stops a render.", file=sys.stderr)
    if parsed is None:
        print(
            f"\nThe date could not be PARSED, which is a different problem "
            f"from a stale one. The gate accepts:\n  "
            + "\n  ".join(_AS_OF_FORMATS)
            + "\n  a raw Excel serial (days since 1899-12-30)\n\n"
              "Either re-save the as-of cell in one of those shapes — "
              "ISO `YYYY-MM-DD` is what the template asks for — or, if the "
              "shape your locale writes is a reasonable one this list is "
              "missing, add it to `_AS_OF_FORMATS` in pipeline/gates.py "
              "rather than turning the gate off.",
            file=sys.stderr)
    else:
        print(f"\nThe date READ fine ({parsed.isoformat()}) and is simply "
              f"older than {settings.data_max_age_days} days. Refresh the "
              f"workbook and upload it again.", file=sys.stderr)
    print("\n`DATA_STALE_BLOCKS=false` makes both cases advisory. That is a "
          "decision about publishing old numbers as current, not a way "
          "around a parsing problem.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
