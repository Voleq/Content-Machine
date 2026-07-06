"""Master-prompt filling: the operator never hand-assembles a prompt.
`/new` (after the data upload) returns both templates with {{ticker}},
{{as_of_date}}, {{company_data}}, {{move_context}}, {{meme_keys}},
{{doodle_keys}}, {{broll_palette}}, {{chart_metrics}} and
{{screenshot_files}} already injected — ready to paste into Claude/GPT.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import Settings
from pipeline.broll import palette_keys
from pipeline.company_data import list_screenshots
from pipeline.doodles import DoodleLibrary
from pipeline.memes import MemeLibrary
from pipeline.models import CompanyData
from pipeline.parser_long import CHART_METRICS


def fill_prompt(
    fmt: str,
    ticker: str,
    data: CompanyData,
    workspace: Path,
    settings: Settings,
    move_context: str = "",
) -> str:
    template_file = settings.templates_dir / f"master_prompt_{fmt}.md"
    text = template_file.read_text()

    as_of = data.get("as_of_date") or date.today().isoformat()
    replacements = {
        "{{ticker}}": ticker.upper(),
        "{{as_of_date}}": str(as_of),
        "{{company_data}}": data.as_prompt_block(),
        "{{meme_keys}}": ", ".join(MemeLibrary(settings).keys()) or "(library empty)",
        "{{doodle_keys}}": ", ".join(DoodleLibrary(settings).keys()) or "(library empty)",
        "{{broll_palette}}": ", ".join(palette_keys()),
    }
    if fmt == "short":
        replacements["{{move_context}}"] = move_context or (
            "(no screener context — fill in how much it moved today, on what "
            "volume, and the headline that did it)"
        )
    if fmt == "long":
        shots = list_screenshots(workspace)
        replacements["{{chart_metrics}}"] = ", ".join(CHART_METRICS)
        replacements["{{screenshot_files}}"] = (
            ", ".join(shots) if shots else "(none uploaded yet — upload PNGs first)"
        )
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text
