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
    # Asserted, not skipped. These are committed artwork, so an empty family
    # means the last ingest ran without the stings delivery on its command
    # line — the ingest is a full rebuild, so a source left off is a family
    # deleted. That happened, and a skip is what let it through.
    assert strips, (
        "no stings in the kit — re-run the ingest with EVERY delivery in the "
        "one command (see scripts/ingest_kit.py)")
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
    assert strips, "no stings in the kit — see the note above"
    assert {"16:9", "9:16"} <= {a.aspect for a in strips}, \
        "a 9:16 short needs a strip it does not have to crop"


# --------------------------------------------------------------------------
# Micro-motion: f01 IS the base still.
#
# The whole reason the batch was re-exported. Every sequence starts on a byte
# copy of the shot it animates, so a blink can begin on any hold and land back
# on the shot's own pose with nothing moving but the eyelid. Ship a base still
# that went through a lossy re-encode and the property is gone — palette
# quantisation moved every pixel in `at-desk-open` by about a level and 0.85%
# of them by up to 18, which reads as a pop the moment the strip starts.
# --------------------------------------------------------------------------

MOTION_MANIFEST = {
    "family": "host-motion",
    "canvas": {"width": 1600, "height": 900, "exportScale": 1},
    "fps": {"blink": 12, "idle": 8, "idleB": 8},
    "assets": [{
        "name": "chapters/cold-open/at-desk-open",
        "baseStill": "chapters/cold-open/at-desk-open.png",
        "sequences": {
            "blink": {"files": [f"chapters/cold-open/at-desk-open-blink_f0{i}.png"
                                for i in (1, 2, 3)],
                      "frameCount": 3, "fps": 12, "playback": "one-shot"},
            "idle": {"files": [f"chapters/cold-open/at-desk-open-idle_f0{i}.png"
                               for i in (1, 2, 3, 4)],
                     "frameCount": 4, "fps": 8, "playback": "loop"},
            "idleB": {"files": [f"chapters/cold-open/at-desk-open-idle-b_f0{i}.png"
                                for i in (1, 2, 3, 4)],
                      "frameCount": 4, "fps": 8, "playback": "loop"},
        },
    }],
}


def test_the_motion_shape_is_recognised():
    from scripts.ingest_kit import is_host_motion

    assert is_host_motion(MOTION_MANIFEST)
    assert not is_host_motion({"family": "stings",
                               "assets": [{"name": "x", "files": ["x.png"]}]})


def test_each_sequence_registers_beside_the_shot_it_animates(tmp_path):
    """`-blink` next to the shot, not under a `host-motion` family.

    Registered under the delivery's own family the strips would sit somewhere
    nothing looks — the renderer resolves them by asking for `<key>-blink`.
    """
    from scripts.ingest_kit import entries_from_host_motion

    entries, root = entries_from_host_motion(tmp_path / "manifest.json",
                                             MOTION_MANIFEST)
    assert set(entries) == {
        "chapters/cold-open/at-desk-open-blink",
        "chapters/cold-open/at-desk-open-idle",
        "chapters/cold-open/at-desk-open-idle-b",
    }
    blink = entries["chapters/cold-open/at-desk-open-blink"]
    assert blink["family"] == "chapters/cold-open"
    assert blink["baseAsset"] == "chapters/cold-open/at-desk-open"
    assert blink["frameCount"] == 3 and blink["fps"] == 12
    assert blink["frames"][0].endswith("at-desk-open-blink_f01.png")


def test_f01_is_kept_in_the_frame_list(tmp_path):
    """It is a byte copy of the base still and it still has to ship.

    Dropping the duplicate frame is the obvious size saving and it destroys
    the property: the strip could no longer start or stop on the shot's pose.
    """
    from scripts.ingest_kit import entries_from_host_motion

    entries, _ = entries_from_host_motion(tmp_path / "m.json", MOTION_MANIFEST)
    idle = entries["chapters/cold-open/at-desk-open-idle"]
    assert len(idle["frames"]) == 4
    assert idle["frames"][0].endswith("_f01.png")


def test_the_shipped_kit_holds_the_invariant():
    """The real kit, checked the way the ingest checks it."""
    from config import Settings
    from pipeline.kit import load_kit

    kit = load_kit(Settings().assets_dir)
    pairs = kit.micro_motion_pairs()
    assert pairs, "the motion batch is ingested — strips must be registered"
    assert kit.micro_motion_drift() == []


def test_drift_is_detected_when_the_base_is_re_encoded(tmp_path):
    """The failure the check exists for, reproduced.

    A lossless re-save with different bytes is enough: the drawing is
    identical and the property is still gone.
    """
    import json

    from PIL import Image

    from pipeline.kit import Kit

    root = tmp_path / "kit"
    (root / "a").mkdir(parents=True)
    img = Image.new("RGBA", (24, 24), (30, 30, 30, 255))
    img.save(root / "a/shot.png")
    (root / "a/shot-blink_f01.png").write_bytes((root / "a/shot.png").read_bytes())
    for i in (2, 3):
        Image.new("RGBA", (24, 24), (60, 60, 60, 255)).save(
            root / f"a/shot-blink_f0{i}.png")

    def entry(name, frames, base=""):
        e = {"family": "a", "name": name, "frames": frames,
             "frameCount": len(frames), "playback": "static", "fps": 12,
             "canvas": {"w": 24, "h": 24}, "aspect": "1:1", "alpha": True,
             "slots": [], "source": "t"}
        if base:
            e["baseAsset"] = base
        return e

    (root / "kit-registry.json").write_text(json.dumps({
        "kit": "t", "version": 2, "roots": {"t": ""}, "assets": {
            "a/shot": entry("shot", ["a/shot.png"]),
            "a/shot-blink": entry(
                "shot-blink", [f"a/shot-blink_f0{i}.png" for i in (1, 2, 3)],
                base="a/shot"),
        }}), encoding="utf-8")

    assert Kit(root).micro_motion_drift() == [], "byte-identical must pass"

    # Re-encode the base. Same pixels, different bytes.
    Image.open(root / "a/shot.png").save(root / "a/shot.png", optimize=True)
    if (root / "a/shot.png").read_bytes() == (root / "a/shot-blink_f01.png").read_bytes():
        pytest.skip("this Pillow re-encodes to identical bytes")
    drift = Kit(root).micro_motion_drift()
    assert len(drift) == 1 and "not byte-identical" in drift[0]
    assert drift[0] in Kit(root).verify(), "verify() must carry it"


def test_the_convention_alone_is_enough_to_hold_a_strip_to_the_rule(tmp_path):
    """A strip with no `baseAsset` is still checked, off its name."""
    import json

    from PIL import Image

    from pipeline.kit import Kit

    root = tmp_path / "kit"
    (root / "a").mkdir(parents=True)
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(root / "a/shot.png")
    Image.new("RGBA", (8, 8), (9, 9, 9, 255)).save(root / "a/shot-idle_f01.png")
    Image.new("RGBA", (8, 8), (9, 9, 9, 255)).save(root / "a/shot-idle_f02.png")
    e = lambda n, f: {"family": "a", "name": n, "frames": f,  # noqa: E731
                      "frameCount": len(f), "playback": "loop", "fps": 8,
                      "canvas": {"w": 8, "h": 8}, "aspect": "1:1",
                      "alpha": True, "slots": [], "source": "t"}
    (root / "kit-registry.json").write_text(json.dumps({
        "kit": "t", "version": 2, "roots": {"t": ""}, "assets": {
            "a/shot": e("shot", ["a/shot.png"]),
            "a/shot-idle": e("shot-idle", ["a/shot-idle_f01.png",
                                           "a/shot-idle_f02.png"]),
        }}), encoding="utf-8")
    drift = Kit(root).micro_motion_drift()
    assert len(drift) == 1 and drift[0].startswith("a/shot-idle:")
