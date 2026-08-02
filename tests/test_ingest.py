"""`python scripts/ingest_kit.py <delivery>` is the whole procedure.

Landing a delivery used to take hand-work: merging a new family into the
top-level registry by hand, remembering to relight the dark cards afterwards,
and noticing on your own that the delivery had been size-optimised. Each of
those is a step that can be skipped, and two of them fail silently.

The case these exist for is the commissioned `stings/`: a folder arrives with
its own `manifest.json` and has to register with no edit and no code change,
because that is how every future batch of artwork lands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.ingest_kit import (
    _aspect,
    discover_manifests,
    entries_from_manifest,
    palette_offenders,
)

ROOT = Path(__file__).resolve().parents[1]


def _strip(dest: Path, name: str, n: int, size: tuple[int, int]) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(1, n + 1):
        f = f"{name}_f{i:02d}.png"
        Image.new("RGBA", size, (0, 0, 0, 0)).save(dest / f)
        files.append(f)
    return files


@pytest.fixture()
def delivery(tmp_path: Path) -> Path:
    """A folder that has just gained a family with its own manifest."""
    fam = tmp_path / "memes" / "shorts" / "stings"
    wide = _strip(fam, "ink-wipe", 6, (3840, 2160))
    tall = _strip(fam, "ink-wipe-tall", 6, (2160, 3840))
    (fam / "manifest.json").write_text(json.dumps({
        "family": "stings",
        "canvas": {"width": 1920, "height": 1080, "exportScale": 2},
        "fps": 12,
        "assets": [
            {"name": "ink-wipe", "title": "Ink wipe", "files": wide,
             "frameCount": 6, "fps": 12, "playback": "one-shot",
             "canvas": {"width": 1920, "height": 1080}, "slots": []},
            {"name": "ink-wipe-tall", "title": "Ink wipe (tall)", "files": tall,
             "frameCount": 6, "fps": 12, "playback": "one-shot",
             "canvas": {"width": 1080, "height": 1920}, "slots": []},
        ],
    }), encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# A family that brings its own manifest registers itself.
# --------------------------------------------------------------------------


def test_a_manifest_anywhere_under_the_delivery_is_found(delivery):
    found = discover_manifests([delivery])
    assert len(found) == 1
    assert found[0][1]["family"] == "stings"


def test_the_manifests_own_family_is_the_key_not_its_folder(delivery):
    """`stings/` arrived nested three deep and still has to register as
    `stings/<name>` — that is the key `transition_asset` looks for."""
    mpath, data = discover_manifests([delivery])[0]
    entries, root = entries_from_manifest(mpath, data)
    assert set(entries) == {"stings/ink-wipe", "stings/ink-wipe-tall"}
    assert root.name == "stings"


def test_the_entry_carries_what_the_player_needs(delivery):
    mpath, data = discover_manifests([delivery])[0]
    entries, _ = entries_from_manifest(mpath, data)
    e = entries["stings/ink-wipe"]
    assert e["frameCount"] == 6
    assert e["playback"] == "one-shot"
    assert e["fps"] == 12
    assert e["exportScale"] == 2, "the 2x export is the trap slots fall into"
    assert e["aspect"] == "16:9"
    assert e["frames"][0] == "stings/ink-wipe_f01.png"


def test_a_per_asset_canvas_overrides_the_familys(delivery):
    """The tall variants share a manifest with the wide ones."""
    mpath, data = discover_manifests([delivery])[0]
    entries, _ = entries_from_manifest(mpath, data)
    assert entries["stings/ink-wipe-tall"]["aspect"] == "9:16"


def test_a_manifest_with_no_assets_is_ignored(tmp_path):
    (tmp_path / "manifest.json").write_text('{"family": "x"}', encoding="utf-8")
    assert discover_manifests([tmp_path]) == []


def test_unreadable_manifests_do_not_stop_the_ingest(tmp_path, capsys):
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    assert discover_manifests([tmp_path]) == []


def test_aspect_is_derived_from_the_canvas():
    assert _aspect(1920, 1080) == "16:9"
    assert _aspect(1080, 1920) == "9:16"
    assert _aspect(1080, 1080) == "1:1"
    assert _aspect(0, 0) == ""


# --------------------------------------------------------------------------
# Full fidelity, checked rather than assumed.
# --------------------------------------------------------------------------


def test_palette_pngs_are_named(tmp_path):
    """A palette PNG hard-quantises the antialiased edges the kit is drawn
    with, and the line work IS the artwork. It also only ever surfaced as a
    Pillow warning at render time."""
    rgba = tmp_path / "good.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(rgba)
    pal = tmp_path / "bad.png"
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).convert("P").save(pal)

    bad = palette_offenders({"a": rgba, "b": pal})
    assert len(bad) == 1
    assert "bad.png" in bad[0] and "(P)" in bad[0]


def test_an_all_rgba_delivery_has_no_offenders(delivery):
    pngs = {p.name: p for p in delivery.rglob("*.png")}
    assert palette_offenders(pngs) == []


# --------------------------------------------------------------------------
# The kit that ships.
# --------------------------------------------------------------------------


def test_the_stings_family_landed_through_the_manifest_route():
    """The concrete acceptance for the whole item: the commissioned strips
    are addressable, and no registry entry for them was written by hand."""
    from pipeline.kit import load_kit

    kit = load_kit(ROOT / "assets")
    strips = kit.family("stings")
    if not strips:
        pytest.skip("stings have not been ingested into this checkout")
    assert len(strips) >= 8
    for key in strips:
        asset = kit.get(key)
        assert asset.frame_count > 1, f"{key} is not a sequence"
        assert asset.playback == "one-shot"
        assert asset.export_scale == 2
        assert kit.path(key) is not None


def test_the_stings_ship_both_orientations():
    from pipeline.kit import load_kit

    kit = load_kit(ROOT / "assets")
    strips = [kit.get(k) for k in kit.family("stings")]
    if not strips:
        pytest.skip("stings have not been ingested into this checkout")
    assert {"16:9", "9:16"} <= {a.aspect for a in strips}, \
        "a 9:16 short needs a strip it does not have to crop"
