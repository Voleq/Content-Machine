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


def test_every_offered_key_resolves_to_real_artwork(settings, kit):
    """The whole point: nothing is offered that the renderer can't find."""
    catalog = kit_catalog(settings)
    checked = 0
    for header, tag in (("[TERM: key]", TagType.TERM),
                        ("[BIGNUM: key]", TagType.BIGNUM),
                        ("[PROP: key]", TagType.PROP),
                        ("[TABLE: kind]", TagType.TABLE),
                        ("[ALERT: kind]", TagType.ALERT)):
        for key in _section(catalog, header):
            assert kit.resolve(KIT_TAG_FAMILIES[tag], key) is not None, \
                f"{header} offers {key!r}, which resolves to nothing"
            checked += 1
    assert checked > 40, f"only {checked} keys offered — the catalog is empty"


def test_the_families_with_named_artwork_are_all_offered(settings, kit):
    """Drift in the other direction: shipped artwork the model is never told
    about is artwork that goes unused, which is how the library ends up
    feeling incomplete while being full."""
    catalog = kit_catalog(settings)
    for header, tag in (("[TABLE: kind]", TagType.TABLE),
                        ("[ALERT: kind]", TagType.ALERT)):
        offered = set(_section(catalog, header))
        on_disk = {n.rsplit("/", 1)[-1]
                   for fam in KIT_TAG_FAMILIES[tag] for n in kit.family(fam)}
        assert on_disk <= offered, \
            f"{header} does not offer: {sorted(on_disk - offered)}"


def test_the_short_catalog_carries_the_whole_beat_library(settings, kit):
    """51 assets, 74 slots, 27 animated — and the SHORT writer had never been
    shown any of it, so every script reached for the same four beats."""
    catalog = kit_catalog(settings, fmt="short")
    assert "SHORT BEAT LIBRARY" in catalog
    for family in ("dennis-vs-numbers", "vertical-scenes", "transformations",
                   "the-world", "open-close"):
        assert f"  {family}:" in catalog, family
    # slot names are what the writer supplies, so they have to be named
    assert "7 slots: rain-1" in catalog
    assert "6f loop" in catalog and "8f one-shot" in catalog


def test_a_new_asset_shows_up_without_a_code_change(settings, kit, monkeypatch):
    """Generated at fill time, so adding artwork is enough."""
    before = kit_catalog(settings)
    assert "brand-new-idea" not in before

    real = load_kit

    def patched(assets_dir):
        from dataclasses import replace

        k = real(assets_dir)
        template = k.get("blanks/term-card-blank")
        k._assets["blanks/term-brand-new-idea"] = replace(
            template, key="blanks/term-brand-new-idea",
            name="term-brand-new-idea")
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


def test_the_chapter_kits_are_named_from_the_registry(settings, kit):
    """Named from the families that ship artwork, so a new chapter kit is
    offered without a code change and a container is never named as one."""
    kits = _chapter_kits(kit)
    assert "chapters" not in kits
    for chapter in ("moat", "valuation", "the-numbers", "resigned-close",
                    "guidance-estimates"):
        assert chapter in kits, kits


def test_concepts_carry_a_use_when_because_their_names_do_not_say(settings):
    catalog = kit_catalog(settings)
    lines = [ln for ln in catalog.splitlines() if ln.strip().startswith("- ")]
    assert lines, "concepts should be listed one per line with a gloss"
    assert any("value-trap-trap" in ln and "—" in ln for ln in lines)


# --------------------------------------------------------------------------
# Terse enough to actually inject.
# --------------------------------------------------------------------------


def test_it_stays_a_menu_not_a_dump_of_every_frame(settings, kit):
    """A 594-frame dump would swamp the prompt it is meant to inform.

    The SHORT gets a larger budget on purpose: its beat library is the half of
    the kit the writer has to be able to name, and each entry earns its line by
    carrying the slots it takes.
    """
    assert len(kit) >= 384, "sanity: the kit really is that big"
    long_catalog = kit_catalog(settings, fmt="long")
    assert len(long_catalog) < 5000, f"long catalog is {len(long_catalog)} chars"
    assert len(long_catalog.splitlines()) < 70
    short_catalog = kit_catalog(settings, fmt="short")
    assert len(short_catalog) < 9000, f"short catalog is {len(short_catalog)} chars"
    assert len(short_catalog.splitlines()) < 130


def test_the_short_and_long_catalogs_differ_where_they_should(settings):
    short = kit_catalog(settings, fmt="short")
    long = kit_catalog(settings, fmt="long")
    # the beat library is a SHORT concern; chapter kits are a LONG one
    assert "SHORT BEAT LIBRARY" in short and "SHORT BEAT LIBRARY" not in long
    assert "Chapter kits" in long and "Chapter kits" not in short
    # the tag families are the same in both
    for header in ("[TERM: key]", "[PROP: key]", "[ALERT: kind]"):
        assert header in short and header in long


def test_a_missing_kit_says_so_and_points_at_the_escape_hatch(settings, tmp_path):
    """Off a fresh clone the kit isn't exported yet. The prompt must not claim
    an empty library is the whole library."""
    s = settings.model_copy(update={"assets_dir": tmp_path / "nothing"})
    catalog = kit_catalog(s)
    assert "not ingested" in catalog
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
    assert "[PROP: key]" in text
    assert "[BEAT]" in text
    assert "6-8 seconds" in text


def test_the_angle_prompt_does_not_carry_it(settings, workspace):
    """Step 1 picks an angle; it writes no tags, so the catalog is noise there."""
    from pipeline.company_data import load_company_data

    text = fill_prompt("long_angle", "EXMPL", load_company_data(workspace),
                       workspace, settings)
    assert "{{kit_catalog}}" not in text
    assert "[PROP: key]" not in text


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
