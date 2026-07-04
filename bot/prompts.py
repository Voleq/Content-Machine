"""Master-prompt filling (§5.4): the operator never hand-assembles a
prompt. `/new` (after the Refinitiv upload) returns both templates with
{{ticker}}, {{as_of_date}}, {{refinitiv_data}}, {{broll_palette}} and
{{screenshot_files}} already injected — ready to paste into Claude/GPT.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import Settings
from pipeline.broll import palette_keys
from pipeline.models import RefinitivAudit
from pipeline.refinitiv import list_screenshots


def fill_prompt(
    fmt: str,
    ticker: str,
    audit: RefinitivAudit,
    workspace: Path,
    settings: Settings,
) -> str:
    template_file = settings.templates_dir / f"master_prompt_{fmt}.md"
    text = template_file.read_text()

    as_of = audit.get("as_of_date") or date.today().isoformat()
    replacements = {
        "{{ticker}}": ticker.upper(),
        "{{as_of_date}}": str(as_of),
        "{{refinitiv_data}}": audit.as_prompt_block(),
    }
    if fmt == "long":
        shots = list_screenshots(workspace)
        replacements["{{broll_palette}}"] = ", ".join(palette_keys())
        replacements["{{screenshot_files}}"] = (
            ", ".join(shots) if shots else "(none uploaded yet — upload PNGs first)"
        )
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text
