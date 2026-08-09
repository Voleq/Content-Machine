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
    BEAT_SITUATIONS,
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
    feeling incomplete while being full.

    "Named artwork" means artwork the renderer will PLACE. A card whose baked
    chip and disclaimer cannot be stripped is refused at placement — offering it
    would steer a writer into a blocking gate finding, which is drift of a worse
    kind than not being told about it.
    """
    catalog = kit_catalog(settings)
    for header, tag in (("[TABLE: kind]", TagType.TABLE),
                        ("[ALERT: kind]", TagType.ALERT)):
        offered = set(_section(catalog, header))
        on_disk = {n.rsplit("/", 1)[-1]
                   for fam in KIT_TAG_FAMILIES[tag] for n in kit.family(fam)
                   if kit.placeable(n)}
        assert on_disk <= offered, \
            f"{header} does not offer: {sorted(on_disk - offered)}"
        stuck = {n.rsplit("/", 1)[-1]
                 for fam in KIT_TAG_FAMILIES[tag] for n in kit.family(fam)
                 if not kit.placeable(n)}
        assert not (stuck & offered), \
            f"{header} offers cards the renderer refuses: {sorted(stuck & offered)}"


def test_the_short_catalog_carries_the_whole_beat_library(settings, kit):
    """51 assets, 74 slots, 27 animated — and the SHORT writer had never been
    shown any of it, so every script reached for the same four beats."""
    catalog = kit_catalog(settings, fmt="short")
    assert "SHORT BEAT LIBRARY" in catalog
    # slot names are what the writer supplies, so they have to be named — and
    # named the way they are TYPED, after the `=`, not counted.
    assert "takes rain-1" in catalog
    assert "6f loop" in catalog and "8f one-shot" in catalog


# --------------------------------------------------------------------------
# The beat library is grouped by SITUATION, not by folder.
# --------------------------------------------------------------------------


def test_every_situation_heading_holds_at_least_one_asset(settings):
    """A heading with nothing under it is a menu section that teaches the
    writer the library is thinner than it is."""
    library = _library_sections(kit_catalog(settings, fmt="short"))
    assert set(library) == set(BEAT_SITUATIONS), \
        f"headings drifted: {sorted(set(BEAT_SITUATIONS) ^ set(library))}"
    for heading, rows in library.items():
        assert rows, f"{heading!r} is an empty heading"


def test_every_placeable_beat_asset_appears_under_exactly_one_heading(settings, kit):
    """The listing is a PARTITION of what `[PROP]` can reach.

    Both halves matter. An asset under two headings is a menu that reads as a
    bigger library than it is; an asset under none is artwork the writer is
    never told about, which is the whole defect this replaces.
    """
    library = _library_sections(kit_catalog(settings, fmt="short"))
    listed = [row.split(" — ")[0] for rows in library.values() for row in rows]
    assert len(listed) == len(set(listed)), \
        f"listed twice: {sorted({k for k in listed if listed.count(k) > 1})}"

    reachable = {
        key.rsplit("/", 1)[-1]
        for fam in KIT_TAG_FAMILIES[TagType.PROP] if fam.startswith("shorts/")
        for key in kit.family(fam) if kit.placeable(key)
    }
    assert reachable, "sanity: the shorts families are routed to [PROP]"
    assert set(listed) == reachable, \
        f"not listed: {sorted(reachable - set(listed))}; " \
        f"listed but unreachable: {sorted(set(listed) - reachable)}"


def test_it_only_offers_beats_the_prop_tag_can_actually_resolve(settings, kit):
    """`shorts/the-world` and `shorts/open-close` are NOT routed to [PROP] —
    the renderer places the desk and the signature open/close itself. The
    catalog listed all six anyway, so it offered keys that resolve to nothing.
    """
    catalog = kit_catalog(settings, fmt="short")
    for key in ("d-desk-wide", "d-desk-empty", "e-open", "e-close"):
        assert kit.resolve(KIT_TAG_FAMILIES[TagType.PROP], key) is None, \
            f"{key} now resolves — this test is stale, not the catalog"
        assert f"- {key} —" not in catalog, f"{key} is offered and resolves to nothing"
    for row in (r for rows in _library_sections(catalog).values() for r in rows):
        key = row.split(" — ")[0]
        assert kit.resolve(KIT_TAG_FAMILIES[TagType.PROP], key) is not None, \
            f"the beat library offers {key!r}, which resolves to nothing"


def test_a_new_shorts_asset_is_grouped_with_no_code_change(settings, tmp_path):
    """Registry drift, the property that matters most.

    The generator's best quality is that adding artwork never needs a code
    change. A hand-maintained key -> situation table would cost exactly that,
    so this adds an asset to a real registry — off disk, through the real read
    path — and expects it to arrive in the catalog, under a heading, unaided.
    """
    import json

    src = ROOT / "assets" / "kit"
    dst = tmp_path / "assets" / "kit"
    dst.mkdir(parents=True)
    for child in src.iterdir():
        if child.is_dir():
            (dst / child.name).symlink_to(child)

    registry = json.loads((src / "kit-registry.json").read_text(encoding="utf-8"))
    entry = dict(registry["assets"]["shorts/dennis-vs-numbers/stand-in-hole"])
    entry["name"] = "brand-new-hole"
    entry["title"] = "An even deeper hole"
    registry["assets"]["shorts/dennis-vs-numbers/brand-new-hole"] = entry
    (dst / "kit-registry.json").write_text(json.dumps(registry), encoding="utf-8")

    s = settings.model_copy(update={"assets_dir": tmp_path / "assets"})
    library = _library_sections(kit_catalog(s, fmt="short"))
    placed = [h for h, rows in library.items()
              if any(r.startswith("brand-new-hole ") for r in rows)]
    assert placed == ["ONE figure, and it went the wrong way"], \
        f"the new drawing landed under {placed}"


def test_the_short_catalog_shows_how_to_write_a_value(settings, kit):
    """A key on its own renders the drawing with its boxes empty, so the
    syntax has to be in front of the writer, not just in the prompt."""
    catalog = kit_catalog(settings, fmt="short")
    assert "[PROP: crushed-flat = -41%]" in catalog
    assert "heavy:$1.1B" in catalog, "the named form has to be shown"
    assert "EMPTY" in catalog, "and what happens without it"


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
    """Named from the families that ship PLACEABLE artwork, so a new chapter kit
    is offered without a code change and a container is never named as one.

    A family whose every drawing keeps its baked furniture has nothing the
    renderer will place, so promising the writer "name a chapter close to one of
    these and it gets its own visuals" would be false. Three families are in
    that state until Design redraws them, and they are named here so the day the
    artwork lands this test says what changed.
    """
    kits = _chapter_kits(kit)
    assert "chapters" not in kits
    for chapter in ("valuation", "the-numbers", "resigned-close", "cold-open"):
        assert chapter in kits, kits

    fully_stuck = [f.split("/", 1)[1] for f in kit.families()
                   if f.startswith("chapters/")
                   and kit.family(f) and not any(kit.placeable(k)
                                                 for k in kit.family(f))]
    assert set(fully_stuck) == {"guidance-estimates", "moat", "short-interest"}, \
        f"the fully-stuck families moved: {sorted(fully_stuck)}"
    for chapter in fully_stuck:
        assert chapter not in kits, \
            f"{chapter} is offered but nothing in it can be placed"


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


def _library_sections(catalog: str) -> dict[str, list[str]]:
    """`{situation heading: [row, …]}` for the beat-library block.

    Parsed back out of the rendered catalog rather than read off the helper
    that built it — what the writer is shown is the thing under test.
    """
    out: dict[str, list[str]] = {}
    heading = ""
    inside = False
    for line in catalog.splitlines():
        if "BEAT LIBRARY —" in line:
            inside = True
            continue
        if not inside:
            continue
        if line.startswith("    - "):
            if heading:
                out[heading].append(line[6:].strip())
        elif line.startswith("  ") and line.rstrip().endswith(":"):
            heading = line.strip().rstrip(":")
            out.setdefault(heading, [])
        elif line.startswith("  ") and ":  (" in line:
            heading = line.strip().split(":  (")[0]
            out.setdefault(heading, [])
        elif not line.startswith("  "):
            break
    return out


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
