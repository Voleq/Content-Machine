"""One block, per render, answering a single question: what in this video
was real?

    EXMPL · LONG · 2026-09-12 · 22m14s
    prices    LIVE  yahoo · 120d · as-of 2026-09-11
    visuals   6 pexels · 2 wikimedia · 3 owned · 1 GIF (tenor) · 0 filler
    filings   2 shots · 10-K 0000320193-26-000012
    audio     PAID  eleven_v3 · 1 generation · 9 chunks · $0.94
    llm       LOCAL ollama/gemma4:12b-it-qat · 16 calls · 0 hosted fallbacks
    gates     fact-check ✓ · voice ✓ · direction ✓ · skeptic SKIPPED (no LLM)

THE FAILURE IT EXISTS TO PREVENT is B1: a Yahoo outage produced a seeded
random walk with a deliberate 8-30% spike on the final bar, the `degraded`
flag was dropped by `to_json()`, nothing outside `prices.py` ever read it,
and a fabricated price chart shipped looking exactly like a real one. There
was no surface in the product that could have revealed it.

That shape recurs. A GIF pulled from Tenor rather than the owned library,
uncounted (H3). A filing brief built from half a section because `num_ctx`
truncated it (K2). A gate that returned nothing because the LLM was down
rather than because the script was clean (N2). A Telegram send swallowed by
`push_file`'s exception handler (E3). Each was invisible in the output.

This is a generalisation of `mock_banner`, which is the best instinct in
this codebase — say out loud, every run, which subsystems are inventing
data. It just covered three of them.

**NOT A COMMAND, by design.** The failure mode here is nobody looking. A
`/provenance TICKER` gets typed when you already suspect something is
wrong, which is exactly when you do not need it. Attached to the link you
receive when a render finishes, it arrives whether or not you thought to
ask — the same reasoning as E2, where by-product links were computed every
run and never surfaced.

Nearly all of this data already existed and was being thrown away. The
record is plumbing, not measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# `Visual.source` was already exactly the right vocabulary; this only says
# which bucket each value belongs in.
_OWNED = {"local", "library"}
_GIF = {"giphy", "tenor", "imgflip"}
_FAKE = {"mock", "generated"}


def _mmss(seconds: float) -> str:
    total = int(round(seconds or 0))
    return f"{total // 60}m{total % 60:02d}s"


@dataclass
class Provenance:
    """What was real in one render. Serialised onto the manifest as-is."""

    ticker: str = ""
    fmt: str = ""
    workdate: str = ""
    duration_s: float = 0.0

    prices: dict = field(default_factory=dict)
    visuals: dict = field(default_factory=dict)
    filings: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    gates: str = ""

    def to_json(self) -> dict:
        return {
            "ticker": self.ticker, "format": self.fmt,
            "workdate": self.workdate,
            "duration_s": round(self.duration_s, 3),
            "prices": self.prices, "visuals": self.visuals,
            "filings": self.filings, "audio": self.audio,
            "llm": self.llm, "gates": self.gates,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Provenance":
        return cls(
            ticker=str(data.get("ticker") or ""),
            fmt=str(data.get("format") or ""),
            workdate=str(data.get("workdate") or ""),
            duration_s=float(data.get("duration_s") or 0.0),
            prices=dict(data.get("prices") or {}),
            visuals=dict(data.get("visuals") or {}),
            filings=dict(data.get("filings") or {}),
            audio=dict(data.get("audio") or {}),
            llm=dict(data.get("llm") or {}),
            gates=str(data.get("gates") or ""),
        )

    # ---------------------------------------------------------------- lines
    def render_text(self) -> str:
        """The block, as the operator receives it beside the link.

        Every line is derivable from `to_json()` and nothing else, so the
        manifest and the message cannot drift — `tests/test_provenance.py`
        holds that.
        """
        head = " · ".join(p for p in (
            self.ticker, self.fmt.upper(), self.workdate,
            _mmss(self.duration_s) if self.duration_s else "") if p)
        lines = [head]
        for label, body in (("prices", self._prices_line()),
                            ("visuals", self._visuals_line()),
                            ("filings", self._filings_line()),
                            ("audio", self._audio_line()),
                            ("llm", self._llm_line()),
                            ("gates", self.gates)):
            if body:
                lines.append(f"{label:<9} {body}")
        return "\n".join(lines)

    def _prices_line(self) -> str:
        if not self.prices:
            return ""
        src = str(self.prices.get("source") or "unknown")
        if self.prices.get("degraded"):
            # The one line that is not informational. Said in the strongest
            # words the block has, because the chart it describes is
            # indistinguishable from a real one on screen.
            return f"SYNTHETIC  {src} — NOT market data"
        bits = [f"LIVE  {src}"]
        if self.prices.get("days"):
            bits.append(f"{self.prices['days']}d")
        if self.prices.get("as_of"):
            bits.append(f"as-of {self.prices['as_of']}")
        return " · ".join(bits)

    def _visuals_line(self) -> str:
        counts = self.visuals or {}
        if not counts:
            return ""
        owned = sum(n for s, n in counts.items() if s in _OWNED)
        gifs = {s: n for s, n in counts.items() if s in _GIF}
        fake = sum(n for s, n in counts.items() if s in _FAKE)
        bits = [f"{n} {s}" for s, n in sorted(counts.items())
                if s not in _OWNED | _GIF | _FAKE | {"filler"}]
        if owned:
            bits.append(f"{owned} owned")
        for src, n in sorted(gifs.items()):
            bits.append(f"{n} GIF ({src})")
        if fake:
            bits.append(f"{fake} generated")
        bits.append(f"{counts.get('filler', 0)} filler")
        return " · ".join(bits)

    def _filings_line(self) -> str:
        f = self.filings or {}
        if not f:
            return ""
        bits = []
        if f.get("shots") is not None:
            bits.append(f"{f['shots']} shots")
        for ref in (f.get("refs") or []):
            bits.append(str(ref))
        brief = f.get("brief") or {}
        if brief:
            sections = brief.get("sections")
            held = brief.get("context_held")
            note = f"brief: {sections} sections" if sections else "brief"
            if held is False:
                # K2's failure mode, said out loud: a brief built from half
                # a section reads exactly like one built from all of it.
                note += ", CONTEXT TRUNCATED"
            elif held is True:
                note += ", full context"
            bits.append(note)
        return " · ".join(bits)

    def _audio_line(self) -> str:
        a = self.audio or {}
        if not a:
            return ""
        tier = str(a.get("tier") or "")
        paid = tier == "paid"
        head = "PAID " if paid else ("DRAFT" if a.get("draft") else "FREE ")
        bits = [f"{head} {a.get('model') or tier or 'unknown'}"]
        if a.get("chunks"):
            bits.append(f"{a['chunks']} chunks")
        if a.get("cached"):
            bits.append("cached — $0.00")
        elif a.get("cost_usd") is not None:
            bits.append(f"${float(a['cost_usd']):.2f}")
        return " · ".join(bits)

    def _llm_line(self) -> str:
        m = self.llm or {}
        if not m:
            return ""
        provider = str(m.get("provider") or "")
        if not provider:
            skipped = m.get("skipped") or []
            return f"none ran ({', '.join(sorted(set(skipped)))})" if skipped else ""
        where = "LOCAL" if provider == "ollama" else "HOSTED"
        bits = [f"{where} {provider}/{m.get('model') or '?'}",
                f"{m.get('calls', 0)} calls"]
        fallbacks = int(m.get("hosted_fallbacks") or 0)
        if fallbacks:
            # A brief generated on your own GPU and one that quietly cost
            # money were indistinguishable in every output the product
            # produced (N2b).
            bits.append(f"{fallbacks} HOSTED FALLBACKS")
        return " · ".join(bits)


def build(*, ticker: str, fmt: str, workdate: str, duration_s: float,
          prices=None, visual_sources: dict | None = None,
          filings: dict | None = None, tts=None, gate_report=None,
          settings=None) -> Provenance:
    """Assemble the record from what the render already has in hand."""
    from pipeline.llm import llm_summary

    p = Provenance(ticker=ticker, fmt=fmt, workdate=workdate,
                   duration_s=duration_s)
    if prices is not None:
        p.prices = {
            "source": getattr(prices, "source", ""),
            "degraded": bool(getattr(prices, "degraded", False)),
            "days": len(getattr(prices, "closes", []) or []) or None,
            "as_of": (getattr(prices, "dates", []) or [""])[-1],
        }
    p.visuals = dict(visual_sources or {})
    p.filings = dict(filings or {})
    if tts is not None:
        p.audio = {
            "tier": getattr(tts, "tier", ""),
            "model": getattr(tts, "model_id", "") or getattr(tts, "tier", ""),
            "draft": bool(getattr(tts, "draft", False)),
            "cached": bool(getattr(tts, "cached", False)),
            "cost_usd": float(getattr(tts, "cost_usd", 0.0) or 0.0),
            "chunks": getattr(tts, "chunks", None),
        }
    if settings is not None:
        p.llm = llm_summary(settings)
    if gate_report is not None:
        p.gates = gate_report.ran_line()
    return p
