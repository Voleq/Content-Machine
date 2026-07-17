"""Master-prompt filling: the operator never hand-assembles a prompt.

`/new` (after the data upload) returns the SHORT prompt and the LONG
*angle* prompt (Step 1) with every {{placeholder}} injected — the full
dataset, the voice bible, and the full doodle / meme / b-roll / screenshot
/ chart-metric catalogs — ready to paste into Claude/GPT. After the
operator replies with an angle, `fill_prompt("long_write", …)` returns the
LONG *write* prompt (Step 2) pre-filled with the chosen angle.

The catalogs are injected verbatim so the director SELECTS from real,
existing keys (validated on paste-back) and picks the numbers that decide
the story from the real data — the human decision is the ANGLE, not the
plumbing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import Settings
from pipeline.broll import PALETTE, palette_keys
from pipeline.company_data import list_screenshots
from pipeline.doodles import DoodleLibrary
from pipeline.memes import MemeLibrary
from pipeline.models import CompanyData


def voice_bible(settings: Settings) -> str:
    """The tone anchor (assets/voice_bible.md), injected verbatim."""
    f = settings.assets_dir / "voice_bible.md"
    return f.read_text().strip() if f.exists() else "(voice bible missing)"


def doodle_catalog(settings: Settings) -> str:
    """Every doodle key + its 'use when', grouped by section — the full
    catalog the director picks from (keys must exist; validated on paste)."""
    idx = DoodleLibrary(settings).index()
    if not idx:
        return "(doodle library empty)"
    by_section: dict[str, list[str]] = {}
    for stem in sorted(idx):
        meta = idx[stem]
        section = meta.get("section") or "misc"
        use = (meta.get("use_when") or "").strip()
        by_section.setdefault(section, []).append(
            f"  - {stem}" + (f" — {use}" if use else "")
        )
    lines: list[str] = []
    for section in sorted(by_section):
        lines.append(f"[{section}]")
        lines.extend(by_section[section])
    return "\n".join(lines)


def meme_catalog(settings: Settings) -> str:
    """Every meme key + its 'use when' — the full catalog (capped in use)."""
    idx = MemeLibrary(settings).index()
    if not idx:
        return "(meme library empty)"
    lines = []
    for key in sorted(idx):
        use = (idx[key].get("use_when") or "").strip()
        lines.append(f"  - {key}" + (f" — {use}" if use else ""))
    return "\n".join(lines)


def broll_catalog() -> str:
    """The vetted b-roll palette: key — the search it maps to."""
    return "\n".join(f"  - {k} — {PALETTE[k]}" for k in palette_keys())


def chart_metrics_line(data: CompanyData) -> str:
    """Only metrics with a real multi-year series in THIS data (+ price)."""
    return ", ".join(data.available_chart_metrics())


def _pct(v) -> str:
    """A stored fraction (0.074) rendered as a percent (7.4%); n/a when absent."""
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "n/a"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def valuation_data_block(data: CompanyData) -> str:
    """The reverse-DCF figures for the MANDATORY valuation beat — a perpetuity
    gut-check ("priced for X, has delivered Y"), never a fair value. Exact
    numbers so the writer can cite them instead of guessing."""
    v = data.valuation or {}
    keys = ("implied_growth", "wacc", "hist_fcf_cagr", "rev_cagr", "priced_vs_delivered")
    if not any(v.get(k) is not None for k in keys) and not v.get("reverse_dcf_read"):
        return ("(no reverse-DCF in this export — keep the valuation beat qualitative: "
                "what the current price assumes vs what the business has delivered)")
    lines = [
        'Reverse-DCF — a perpetuity gut-check ("priced for X, has delivered Y"), NOT a fair value:',
        f"  Implied growth priced into today's price (perpetual FCF growth): {_pct(v.get('implied_growth'))}",
        f"  Discount rate used (WACC): {_pct(v.get('wacc'))}",
        f"  Historical FCF CAGR, 4y — what it has ACTUALLY delivered: {_pct(v.get('hist_fcf_cagr'))}",
        f"  Revenue CAGR, 4y: {_pct(v.get('rev_cagr'))}",
        f"  Priced-for minus delivered (FCF), in growth points: {_pct(v.get('priced_vs_delivered'))}",
    ]
    read = v.get("reverse_dcf_read")
    if read:
        lines.append(f"  Read (verdict): {read}")
    return "\n".join(lines)


def peer_percentiles_block(data: CompanyData) -> str:
    """Where THIS ticker ranks within its peer set, metric by metric — the
    "90th percentile on price, 20th on margins" read the valuation beat folds
    in. `percentile` is a 0–1 fraction; `direction` says which way is good."""
    pcts = data.peer_percentiles or []
    if not pcts:
        return "(no peer-percentile block in this export)"
    lines: list[str] = []
    for p in pcts:
        metric = p.get("metric")
        if not metric:
            continue
        pct = p.get("percentile")
        rank = f"{_ordinal(round(pct * 100))} pctile" if isinstance(pct, (int, float)) else "pctile n/a"
        subj, med = p.get("subject"), p.get("median")
        detail = f"subject {subj} vs peer median {med}" if subj is not None and med is not None else ""
        direction = p.get("direction")
        higher = f"higher is {direction}" if direction else ""
        read = p.get("read")
        bits = [b for b in (rank, detail, higher, read) if b]
        lines.append(f"  {metric}: " + " — ".join(bits))
    return "\n".join(lines) if lines else "(no peer-percentile block in this export)"


def filing_quotes_block(data: CompanyData) -> str:
    """Auto-extracted filing quotes (task 5), surfaced only when present — the
    receipts the smoking-gun walk cites. Degrades to the manual [SHOW FILING]
    flow on the uploaded screenshots when there are none."""
    quotes = getattr(data, "filing_quotes", None) or []
    if not quotes:
        return ("(none auto-extracted — the smoking-gun walk uses [SHOW FILING] on the "
                "uploaded filing screenshots below)")
    lines: list[str] = []
    for q in quotes:
        if isinstance(q, dict):
            text = q.get("quote") or q.get("text") or ""
            src = q.get("source") or q.get("label") or ""
            lines.append(f'  - "{text}"' + (f" ({src})" if src else ""))
        else:
            lines.append(f"  - {q}")
    return "\n".join(lines)


def screenshots_line(workspace: Path) -> str:
    shots = list_screenshots(workspace)
    return ", ".join(shots) if shots else "(none uploaded — upload filing PNGs first)"


def fill_prompt(
    fmt: str,
    ticker: str,
    data: CompanyData,
    workspace: Path,
    settings: Settings,
    move_context: str = "",
    chosen_angle: str = "",
) -> str:
    """Fill one master prompt. `fmt` ∈ {short, long_angle, long_write}.

    Every prompt gets the FULL dataset + the catalogs it needs; the writing
    prompts (short, long_write) additionally get the voice bible. `long_write`
    also gets the operator's {{chosen_angle}}.
    """
    template_file = settings.templates_dir / f"master_prompt_{fmt}.md"
    text = template_file.read_text()

    as_of = data.get("as_of_date") or date.today().isoformat()
    r: dict[str, str] = {
        "{{ticker}}": ticker.upper(),
        "{{as_of_date}}": str(as_of),
        "{{company_data}}": data.as_prompt_block(),
        "{{chart_metrics}}": chart_metrics_line(data),
    }

    if fmt == "short":
        r["{{move_context}}"] = move_context or (
            "(no screener context — fill in how much it moved today, on what "
            "volume, and the headline that did it)"
        )
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
    elif fmt == "long_angle":
        r["{{available_screenshots}}"] = screenshots_line(workspace)
        r["{{valuation_data}}"] = valuation_data_block(data)
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
        r["{{filing_quotes}}"] = filing_quotes_block(data)
    elif fmt == "long_write":
        r["{{chosen_angle}}"] = chosen_angle.strip() or "(operator did not specify — use your ★recommended angle)"
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{available_screenshots}}"] = screenshots_line(workspace)
        r["{{valuation_data}}"] = valuation_data_block(data)
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
        r["{{filing_quotes}}"] = filing_quotes_block(data)
    else:
        raise ValueError(f"unknown prompt fmt {fmt!r}")

    for k, v in r.items():
        text = text.replace(k, v)
    return text
