"""The kit catalog injected into the master prompts (addendum 1e).

The writing model was picking tag keys without knowing what artwork exists.
Validation already rejects unknown keys on paste-back, which catches the
mistake — but only after the operator has run a prompt and pasted a script.
Telling the model up front stops the key being invented.

The one property that matters: **the catalog is generated from the manifest,
so it cannot drift from what is on disk.** A hand-maintained list would be
wrong the first time artwork is added, and its failure mode is a script full
of keys that look plausible and resolve to nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.prompts import (
    EXPRESSIVITY_AND_PACING,
    _chapter_kits,
    fill_prompt,
    kit_catalog,
)
from pipeline.kit import load_kit
from pipeline.models import KIT_TAG_FAMILIES, TagType

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def kit(settings):
    return load_kit(settings.assets_dir)


# --------------------------------------------------------------------------
# It matches disk, in both directions.
# --------------------------------------------------------------------------


def test_every_offered_term_resolves_to_real_artwork(settings, kit):
    """The whole point: nothing is offered that the renderer can't find."""
    catalog = kit_catalog(settings)
    section = _section(catalog, "[TERM: key]")
    assert section, "no TERM section in the catalog"
    for key in section:
        assert kit.resolve(KIT_TAG_FAMILIES[TagType.TERM], key) is not None, key


def test_every_offered_prop_table_and_alert_resolves_too(settings, kit):
    for header, tag in (("[PROP: key]", TagType.PROP),
                        ("[TABLE: kind]", TagType.TABLE),
                        ("[ALERT: kind]", TagType.ALERT),
                        ("[BIGNUM: key]", TagType.BIGNUM)):
        keys = _section(catalog := kit_catalog(settings), header)
        assert keys, f"no {header} section"
        for key in keys:
            assert kit.resolve(KIT_TAG_FAMILIES[tag], key) is not None, \
                f"{header} offers {key!r}, which resolves to nothing"
        assert catalog  # silence the walrus lint


def test_it_offers_every_term_card_that_exists(settings, kit):
    """Drift in the other direction: shipped artwork the model is never told
    about is artwork that goes unused, which is how the library ends up feeling
    incomplete while being full."""
    offered = set(_section(kit_catalog(settings), "[TERM: key]"))
    on_disk = {n.split("/")[-1][len("term-"):]
               for n in kit.family("type/callouts")
               if n.split("/")[-1].startswith("term-")}
    on_disk.discard("card-blank")        # the empty layout, offered separately
    assert on_disk <= offered, f"not offered: {sorted(on_disk - offered)}"


def test_a_new_asset_shows_up_without_a_code_change(settings, kit, monkeypatch):
    """Generated at fill time, so adding artwork is enough."""
    before = kit_catalog(settings)
    assert "term-brand-new-idea" not in before

    real = load_kit

    def patched(assets_dir):
        k = real(assets_dir)
        k._assets["type/callouts/term-brand-new-idea"] = {"w": 10, "h": 10}
        k.family.cache_clear()
        return k

    import bot.prompts as prompts_mod
    monkeypatch.setattr(prompts_mod, "load_kit", patched, raising=False)
    import pipeline.kit as kit_mod
    monkeypatch.setattr(kit_mod, "load_kit", patched)

    after = kit_catalog(settings)
    assert "brand-new-idea" in after


def test_the_blank_layouts_are_explained_rather_than_listed_as_frameworks(settings):
    """`term-card-blank` in a list headed 'frameworks that exist' reads as one
    more framework — the exact confusion this is meant to remove."""
    catalog = kit_catalog(settings)
    assert "card-blank" not in _section(catalog, "[TERM: key]")
    assert "blank" not in _section(catalog, "[BIGNUM: key]")
    assert "A blank layout exists" in catalog


def test_the_nested_long_form_chapter_kits_are_named_individually(settings, kit):
    """`chapters/long-form/` is a container for four sub-kits, so listing
    'long-form' would name something that isn't a chapter."""
    kits = _chapter_kits(kit)
    assert "long-form" not in kits
    assert any(k.startswith("long-form/") for k in kits), kits
    assert "moat" in kits and "guidance" in kits


def test_concepts_carry_a_use_when_because_their_names_do_not_say(settings):
    catalog = kit_catalog(settings)
    lines = [ln for ln in catalog.splitlines() if ln.strip().startswith("- ")]
    assert lines, "concepts should be listed one per line with a gloss"
    assert any("value-trap-trap" in ln and "—" in ln for ln in lines)


# --------------------------------------------------------------------------
# Terse enough to actually inject.
# --------------------------------------------------------------------------


def test_it_stays_a_menu_not_a_dump_of_762_frames(settings, kit):
    catalog = kit_catalog(settings)
    assert len(kit) > 700, "sanity: the kit really is that big"
    assert len(catalog) < 6000, f"catalog is {len(catalog)} chars — too long"
    assert len(catalog.splitlines()) < 70


def test_the_short_and_long_catalogs_differ_where_they_should(settings):
    short = kit_catalog(settings, fmt="short")
    long = kit_catalog(settings, fmt="long")
    # beat variants are a SHORT concern; chapter kits are a LONG one
    assert "beat variants" in short and "beat variants" not in long
    assert "Chapter kits" in long and "Chapter kits" not in short
    # the tag families are the same in both
    for header in ("[TERM: key]", "[PROP: key]", "[ALERT: kind]"):
        assert header in short and header in long


def test_a_missing_kit_says_so_and_points_at_the_escape_hatch(settings, tmp_path):
    """Off a fresh clone the kit isn't exported yet. The prompt must not claim
    an empty library is the whole library."""
    s = settings.model_copy(update={"assets_dir": tmp_path / "nothing"})
    catalog = kit_catalog(s)
    assert "not exported" in catalog
    assert "[ASSET]" in catalog


# --------------------------------------------------------------------------
# The escape hatch and the craft rules reach the prompts.
# --------------------------------------------------------------------------


def test_asset_is_framed_as_a_last_resort_not_a_shortcut(settings):
    catalog = kit_catalog(settings)
    assert "[ASSET: slug]" in catalog
    assert "BLOCKS" in catalog, "the render-blocking cost must be stated"
    assert "not a shortcut" in catalog


def test_the_craft_rules_state_the_tags_and_the_pacing():
    for tag in ("[BEAT]", "[SIGH]", "[FLAT]", "[DRY]"):
        assert tag in EXPRESSIVITY_AND_PACING, tag
    assert "never on every sentence" in EXPRESSIVITY_AND_PACING
    assert "OPENS and CLOSES" in EXPRESSIVITY_AND_PACING
    assert "6-8 seconds" in EXPRESSIVITY_AND_PACING


@pytest.mark.parametrize("fmt", ["short", "long_write", "headline"])
def test_every_writing_prompt_carries_the_catalog_and_the_rules(
        fmt, settings, workspace):
    from pipeline.company_data import load_company_data

    data = load_company_data(workspace)
    text = fill_prompt(fmt, "EXMPL", data, workspace, settings,
                       chosen_angle="the value trap", headline="EXMPL falls 9%",
                       headline_mode="company")
    assert "{{kit_catalog}}" not in text, "placeholder left unfilled"
    assert "{{craft_rules}}" not in text
    assert "[TERM: key]" in text
    assert "[BEAT]" in text
    assert "6-8 seconds" in text


def test_the_angle_prompt_does_not_carry_it(settings, workspace):
    """Step 1 picks an angle; it writes no tags, so the catalog is noise there."""
    from pipeline.company_data import load_company_data

    text = fill_prompt("long_angle", "EXMPL", load_company_data(workspace),
                       workspace, settings)
    assert "{{kit_catalog}}" not in text
    assert "[TERM: key]" not in text


def test_no_placeholder_is_left_unfilled_in_any_template(settings, workspace):
    """A stray {{…}} in a prompt is a silent instruction to hallucinate."""
    import re
    from pipeline.company_data import load_company_data

    data = load_company_data(workspace)
    for fmt in ("short", "long_angle", "long_write", "headline"):
        text = fill_prompt(fmt, "EXMPL", data, workspace, settings,
                           chosen_angle="a", headline="b", headline_mode="company")
        leftover = [m for m in re.findall(r"\{\{[a-z_]+\}\}", text)
                    # the templates' own header line explains the mechanism:
                    # "the bot fills every {{placeholder}}" — prose, not a slot
                    if m != "{{placeholder}}"]
        assert not leftover, f"{fmt}: {leftover}"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _section(catalog: str, header: str) -> list[str]:
    """The comma-separated keys under a `header:` line."""
    keys: list[str] = []
    grabbing = False
    for line in catalog.splitlines():
        if line.startswith(header):
            grabbing = True
            continue
        if grabbing:
            if not line.startswith("  ") or line.strip().startswith("- "):
                break
            if line.strip().startswith("A blank layout"):
                continue
            keys += [k.strip() for k in line.split(",") if k.strip()]
    return keys
