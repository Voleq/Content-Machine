"""Owned doodle library + the hand-drawn boil (§doodles): local-only
resolution, tag matching, wobble frames — all offline."""

import json
from pathlib import Path

from PIL import Image

from pipeline.doodles import DoodleLibrary, wobble_frames

ROOT_INDEX_KEYS = 59  # the committed library ships 59 indexed doodles (by section/name)


def test_committed_index_shape(settings):
    lib = DoodleLibrary(settings)
    index = lib.index()
    assert len(index) == ROOT_INDEX_KEYS
    for stem, entry in index.items():
        # keys are "<section>/<name>", kebab-case within each segment
        assert stem == stem.lower().replace(" ", "-"), "keys are kebab-case"
        assert "/" in stem, "doodles keep their section subfolder"
        assert entry.get("tags"), f"{stem} needs tags"
        assert entry.get("use_when"), f"{stem} needs a one-line use_when"
        assert lib._file_for(stem) is not None, f"{stem} has no image file"


def test_index_json_committed_and_valid():
    f = Path(__file__).resolve().parents[1] / "assets" / "doodles" / "doodles_index.json"
    assert len(json.loads(f.read_text())) == ROOT_INDEX_KEYS


def test_match_exact_stem(settings):
    lib = DoodleLibrary(settings)
    assert lib.match("reactions/deadpan") == "reactions/deadpan"


def test_match_by_tag(settings):
    lib = DoodleLibrary(settings)
    assert lib.match("crash") == "poses/panic-run"
    assert lib.match("shrug") == "poses/shrug-idk-man"
    assert lib.match("account-blowup") == "injokes/rip-portfolio"
    assert lib.match("pump") == "annotations/arrow-curved-up"


def test_match_normalizes_key(settings):
    lib = DoodleLibrary(settings)
    assert lib.match("Face Down") == "poses/face-down-defeated"
    assert lib.match("Idk Man") == "poses/shrug-idk-man"


def test_resolve_hit_and_miss(settings):
    lib = DoodleLibrary(settings)
    hit = lib.resolve("shrug")
    assert hit is not None and hit.suffix == ".png"
    assert lib.resolve("definitely-not-a-doodle") is None


def test_doodle_images_are_transparent_overlays(settings):
    """Doodles composite as a top layer, so they must carry alpha."""
    lib = DoodleLibrary(settings)
    path = lib.resolve("circle")
    img = Image.open(path)
    assert img.mode == "RGBA"
    alpha = img.getchannel("A")
    assert alpha.getextrema()[0] == 0, "a crude doodle is mostly transparent"


def test_wobble_frames_are_a_seeded_cycle():
    img = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(img).line([(10, 10), (90, 70)], fill=(255, 255, 255, 255), width=6)
    frames = wobble_frames(img, duration_s=1.0, fps=30, seed="x")
    assert len(frames) == 30
    # frames are held a few at a time (2s-on-ones), then repeat — not 30 uniques
    distinct = {f.tobytes() for f in frames}
    assert 2 <= len(distinct) <= 4
    # padded larger than the source so rotation/shift never clips
    assert frames[0].size[0] > img.width and frames[0].size[1] > img.height
    # deterministic
    again = wobble_frames(img, duration_s=1.0, fps=30, seed="x")
    assert frames[0].tobytes() == again[0].tobytes()
