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
    elif fmt == "long_angle":
        r["{{available_screenshots}}"] = screenshots_line(workspace)
    elif fmt == "long_write":
        r["{{chosen_angle}}"] = chosen_angle.strip() or "(operator did not specify — use your ★recommended angle)"
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{available_screenshots}}"] = screenshots_line(workspace)
    else:
        raise ValueError(f"unknown prompt fmt {fmt!r}")

    for k, v in r.items():
        text = text.replace(k, v)
    return text
