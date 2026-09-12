"""The prompt payload is a table, and the table has to match the templates.

Five master prompts were filled by five hand-written branches in
`fill_prompt`, each listing its own placeholders. That is how you get one
block computed and discarded, another missing where it is needed, and a
third that reaches nobody at all — and all four of M1-M4 were found by
diffing the placeholder sets against the fill branches by hand (M6).

Doing that by hand once finds four. Doing it here finds the fifth, on the
commit that introduces it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bot.prompts import PAYLOAD, PROMPT_FORMATS, payload_tokens

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

# The header's literal `{{placeholder}}` is documentation, not a field.
_TOKEN = re.compile(r"\{\{[a-z_]+\}\}")
_DOC_TOKENS = {"{{placeholder}}"}


def _template_tokens(fmt: str) -> set[str]:
    text = (TEMPLATES / f"master_prompt_{fmt}.md").read_text(encoding="utf-8")
    return set(_TOKEN.findall(text)) - _DOC_TOKENS


@pytest.mark.parametrize("fmt", PROMPT_FORMATS)
def test_the_table_fills_exactly_what_the_template_asks_for(fmt):
    """Both directions, which is the point.

    A token in the template and not in the table reaches the writer as the
    literal `{{token}}`. A block in the table and not in the template is
    computed and thrown away — which is what `{{chapter_types}}` was, on two
    prompts, while `chapter_type_catalogue` read the whole plate registry to
    build it (M1).
    """
    wanted = _template_tokens(fmt)
    filled = payload_tokens(fmt)

    assert not (wanted - filled), \
        f"{fmt} asks for and nothing fills: {sorted(wanted - filled)}"
    assert not (filled - wanted), \
        f"{fmt} is handed and does not contain: {sorted(filled - wanted)}"


def test_no_prompt_is_left_out_of_the_table():
    on_disk = {p.stem.replace("master_prompt_", "")
               for p in TEMPLATES.glob("master_prompt_*.md")}
    assert on_disk == set(PROMPT_FORMATS)


def test_every_block_reaches_at_least_one_prompt():
    orphans = [b.token for b in PAYLOAD if not b.formats]
    assert not orphans, f"built for nobody: {orphans}"


def test_the_long_form_pair_agree_on_what_they_are(settings):
    """M2's shape, as a rule rather than one fix.

    `long_write` and `update` are both 16:9 long-form with the same tag
    grammar, the same parser and the same renderer. Anything one gets and
    the other does not has to be about the SPINE — the angle it was written
    to, or the prior call it is grading — and not about craft, catalogs or
    evidence.
    """
    spine = {"{{chosen_angle}}", "{{prior_coverage}}"}
    only_write = payload_tokens("long_write") - payload_tokens("update")
    only_update = payload_tokens("update") - payload_tokens("long_write")

    assert only_write <= spine, only_write
    assert only_update <= spine, only_update


def test_the_short_gets_the_evidence_for_the_judgement_it_is_asked_for(
        settings, fixtures_dir, tmp_path):
    """M3: beat 8 is cheap-or-trap — "is the multiple a bargain or a trap?"
    — and the short was the one prompt with no valuation block."""
    from pipeline.company_data import load_company_data

    from bot.prompts import fill_prompt

    ws = tmp_path / "ws"
    ws.mkdir()
    import shutil
    shutil.copy(fixtures_dir / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    data = load_company_data(ws)

    text = fill_prompt("short", "EXMPL", data, ws, settings)

    assert "{{valuation_data}}" not in text
    assert "VALUATION DATA" in text


def test_the_news_sheet_reaches_the_writer(settings, fixtures_dir, tmp_path):
    """M5: `CompanyData.news` was read from the workbook and
    `as_prompt_block` did not emit it, so `{{company_data}}` contained zero
    headlines in every prompt — while the SHORT's beat 3 is "the headline(s)
    that caused the move" and the writer was composing it unaided."""
    import shutil

    from pipeline.company_data import load_company_data

    from bot.prompts import fill_prompt

    ws = tmp_path / "ws2"
    ws.mkdir()
    shutil.copy(fixtures_dir / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    data = load_company_data(ws)
    assert data.news, "the fixture workbook has a News sheet"

    text = fill_prompt("short", "EXMPL", data, ws, settings)

    assert "[news ·" in text
    assert data.news[0]["headline"] in text
    # The URL is what `[SHOW ARTICLE]` resolves against server-side, and a
    # model handed one will put it on screen.
    assert data.news[0]["url"] not in text
