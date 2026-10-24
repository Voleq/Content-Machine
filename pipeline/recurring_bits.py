"""The recurring bits (S10): two tools, and two bits that come back now and then.

Bible v3 §6 names four. The footnote nobody read and said-versus-filed are
tools: the writer uses them whenever the filing hands him one, and nothing
here schedules them. Kev's tip and Dennis's old trade are bits, and a bit
that runs every video stops being one — so each comes back every six to
eight longs, at a point in that window drawn once per bit (seeded, so the
same ledger always gives the same answer), and never both in one video.

The old trade is a confession by construction: a trade of his own, what he
did, what the filing would have told him. So it only comes due when the
confession ledger says a confession is due, and when it runs, it IS that
video's confession. The two can never stack.

The writer cannot see the channel's history, so the prompt is told which
bit, if any, this video carries. The ledger is noted at ship time, one row
per long, including the longs that carried neither — the "how long since"
half of the rule is about those.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re

from config import Settings
from pipeline.gates import Finding

log = logging.getLogger(__name__)

BITS_FILE = "recurring_bits.json"
BITS = ("kev_tip", "old_trade")
TOOLS = ("footnote", "said_vs_filed")
# Longs between two runs of one bit: drawn in this window, both ends in.
GAP = (6, 8)

NAMES = {"kev_tip": "Kev's tip", "old_trade": "Dennis's old trade"}
_KEV_RE = re.compile(r"\bKev\b")


class BitLedger:
    """One row per shipped long: {key, ticker, workdate, bit}."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / BITS_FILE

    def rows(self) -> list[dict]:
        from pipeline.standing import _read

        rows = _read(self.path, [])
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict) and r.get("key")]

    def since(self, bit: str) -> int:
        """Longs shipped since this bit last ran; every long when it never has."""
        n = 0
        for row in reversed(self.rows()):
            if row.get("bit") == bit:
                return n
            n += 1
        return n

    def _last_key(self, bit: str) -> str:
        for row in reversed(self.rows()):
            if row.get("bit") == bit:
                return str(row["key"])
        return "start"

    def gap_for(self, bit: str) -> int:
        """How many longs this bit waits this time, in `GAP`. Drawn from the
        bit and its last run, so it is a fresh draw after every run and the
        same draw every time it is asked in between."""
        seed = hashlib.sha256(f"{bit}|{self._last_key(bit)}".encode()).hexdigest()
        return random.Random(int(seed[:12], 16)).randint(*GAP)

    def overdue(self, bit: str) -> int:
        """How far past its gap the bit is: negative while it still waits."""
        return self.since(bit) - self.gap_for(bit)

    def note(self, key: str, ticker: str, workdate: str, bit: str) -> bool:
        """Record one shipped long. A long already on record is left alone."""
        from pipeline.standing import _now, _write

        rows = self.rows()
        if any(r.get("key") == key for r in rows):
            return False
        rows.append({"key": key, "ticker": (ticker or "").upper(),
                     "workdate": workdate, "bit": bit if bit in BITS else "",
                     "recorded_at": _now().isoformat()})
        _write(self.path, rows)
        return True


def _confession_due(settings: Settings) -> bool:
    from pipeline.standing import ConfessionLedger

    try:
        return ConfessionLedger(settings).due()
    except Exception:                              # noqa: BLE001
        return False


def due_bit(settings: Settings, *, confession_due: bool | None = None) -> str:
    """The bit this long carries: "", "kev_tip" or "old_trade".

    `confession_due` overrides the confession ledger's answer; the ship-time
    reading passes True, because by then this video's own confession has
    already been written to the ledger.
    """
    try:
        led = BitLedger(settings)
        late = {bit: led.overdue(bit) for bit in BITS}
    except Exception as e:                         # noqa: BLE001
        log.debug("recurring bits unreadable (%s)", e)
        return ""
    if confession_due is None:
        confession_due = _confession_due(settings)
    ready = [b for b in BITS if late[b] >= 0
             and (b != "old_trade" or confession_due)]
    if not ready:
        return ""
    # Both due: the one further past its window; a tie goes to Kev, because
    # the old trade can wait for the next confession and Kev cannot.
    return max(ready, key=lambda b: (late[b], b == "kev_tip"))


def bits_block(settings: Settings) -> str:
    """{{recurring_bits}}: what this long carries, and what it leaves out."""
    due = due_bit(settings)
    tools = ("The footnote nobody read and said-versus-filed are tools, not "
             "bits: use either wherever the filing hands you one.")
    if due == "kev_tip":
        return (
            "THIS VIDEO CARRIES KEV'S TIP. Kev has texted Dennis a tip about "
            "this company at six in the morning, with \"thoughts?\" — the kind "
            "of claim that goes round TikTok or a barber's chair. Somewhere it "
            "fits (not the hook), Dennis checks it against the filing, on "
            "screen, and it falls apart. It debunks a kind of claim; it never "
            "recommends anything, and Kev's source is a type, never a named "
            "person. Once. The old trade stays out of this one.\n" + tools)
    if due == "old_trade":
        return (
            "THIS VIDEO CARRIES DENNIS'S OLD TRADE, and it is this video's "
            "confession. A trade from his own years (2018 to 2022 — keep to "
            "his story and the facts list) in this company or one like it: "
            "what he did, and what the filing would have told him if he had "
            "read it. Declare it in the `=== CONFESSION ===` trailer as "
            "`financial | …`. Kev stays out of this one.\n" + tools)
    try:
        led = BitLedger(settings)
        ago = ", ".join(f"{NAMES[b]} {led.since(b)} long(s) ago"
                        if any(r.get('bit') == b for r in led.rows())
                        else f"{NAMES[b]} not yet" for b in BITS)
    except Exception:                              # noqa: BLE001
        ago = "the record is unreadable"
    return (f"No recurring bit is due ({ago}). Kev and the old trade stay out "
            f"of this video entirely — they come back every six to eight "
            f"longs, and this is not one.\n" + tools)


def old_trade_line(settings: Settings) -> str:
    """The line the confession block adds when the old trade is due."""
    if due_bit(settings) != "old_trade":
        return ""
    return ("  THIS VIDEO'S CONFESSION IS DENNIS'S OLD TRADE (see the "
            "recurring bits above). Write that one and no other.")


def _kev_sentences(narration: str) -> int:
    return sum(1 for s in re.split(r"(?<=[.!?])\s+|\n+", narration or "")
               if _KEV_RE.search(s))


def detect_bit(narration: str, *, confessed: bool, old_trade_ready: bool,
               kev_due: bool = True) -> str:
    """Which bit a shipped long actually carried.

    A PASSING MENTION IS NOT THE BIT. `bits_lint` lets a long that is not
    Kev's keep him to one line, and that line was recorded as his tip, which
    pushed the real one back six to eight longs (scan, 24 Oct 2026). So when
    the tip was not due, Kev in a single sentence is a mention; in more, the
    writer ran the bit anyway and it counts."""
    kev = _kev_sentences(narration)
    if kev and (kev_due or kev > 1):
        return "kev_tip"
    if confessed and old_trade_ready:
        return "old_trade"
    return ""


def note_long(settings: Settings, key: str, ticker: str, workdate: str,
              script) -> str:
    """Ship time: record which bit this long carried. Returns the bit."""
    narration = getattr(script, "narration", "") or ""
    said = getattr(script, "confession", None)
    confessed = bool(getattr(said, "text", "") if said else "")
    try:
        kev_due = BitLedger(settings).overdue("kev_tip") >= 0
    except Exception:                              # noqa: BLE001
        kev_due = True
    bit = detect_bit(narration, confessed=confessed,
                     old_trade_ready=due_bit(settings, confession_due=True)
                     == "old_trade", kev_due=kev_due)
    BitLedger(settings).note(key, ticker, workdate, bit)
    return bit


def bits_lint(script, settings: Settings) -> list[Finding]:
    """Kev in a long that is not his: the bit came back too soon."""
    if not hasattr(script, "chapter_list"):
        return []                                  # longs only
    narration = getattr(script, "narration", "") or ""
    m = None
    for lineno, line in enumerate(narration.splitlines(), 1):
        m = _KEV_RE.search(line)
        if m:
            break
    if m is None or due_bit(settings) == "kev_tip":
        return []
    try:
        since = BitLedger(settings).since("kev_tip")
    except Exception:                              # noqa: BLE001
        since = 0
    return [Finding(
        gate="bits", severity="warn", line=lineno,
        message=(f"Kev's tip is not due in this video — it comes back every "
                 f"six to eight longs, and the last one was {since} long(s) "
                 f"ago. Take Kev out, or keep him to a passing mention"),
        excerpt=line.strip()[:140])]
