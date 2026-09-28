"""Design's chapter bumper and the wipes the LONG lays over its cuts."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import bumper as B
from pipeline import motion as M


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir)


@pytest.fixture(scope="module")
def frames(reg, settings):
    return B.bumper_frames(reg, settings, aspect="16x9", n=3, total=7,
                           title="Where the cash actually goes",
                           episode="EXMPL · DEEP DIVE", size=(1920, 1080))


def test_the_bumper_is_held_as_long_as_the_plate_says(frames, reg):
    plate = reg.get(reg.aspect_key("structure/chapter-bumper", "16x9"))
    assert len(frames) == round((plate.hold_s or 2.0) * M.FPS) == 24


def test_the_bumper_prints_design_s_count():
    assert B.bumper_values(3, 7, " A title ", "EP") == {
        "num": "03", "of": "OF SEVEN", "title": "A title", "episode": "EP"}
    assert B.spelled(21) == "TWENTY-ONE" or B.spelled(21) == "TWENTY ONE"


def _num_box(reg):
    plate = reg.get(reg.aspect_key("structure/chapter-bumper", "16x9"))
    s = plate.export_scale
    sl = plate.slots["num"]
    k = 1920 / plate.pixel_size[0]
    return tuple(int(v * s * k) for v in (sl.x, sl.y, sl.x + sl.w, sl.y + sl.h))


def test_the_number_turns_over_and_nothing_else_changes(frames, reg):
    box = _num_box(reg)
    first, _ = B.tick_timing(reg, reg.get(reg.aspect_key("structure/chapter-bumper", "16x9")))
    assert first == 3, "design's tick-over starts on the fourth frame of the hold"
    a = [np.asarray(f.convert("RGB"), dtype=np.int16) for f in frames]
    # Before the tick the old number holds; after six frames the new one does.
    assert np.abs(a[0] - a[first]).max() < 60      # boil only
    inside = lambda i, j: np.abs(a[i] - a[j])[box[1]:box[3], box[0]:box[2]].mean()
    assert inside(first, first + 6) > 5
    assert inside(first + 6, len(a) - 1) < 3
    # Outside the number, the frames differ only by the plate's own boil.
    outside = np.abs(a[first] - a[first + 3]).copy()
    outside[box[1]:box[3], box[0]:box[2]] = 0
    assert outside.mean() < 3


def test_nothing_on_the_bumper_fades(frames):
    for f in frames:
        alpha = np.asarray(f)[:, :, 3]
        assert alpha.min() == 255, "the bumper is a full frame"


def test_a_wipe_puts_its_full_cover_on_the_cut(reg, tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr("pipeline.rasters.frames_to_alpha_clip",
                        lambda fr, fps, out: got.setdefault("n", (len(fr), fps)) and out)
    clip = B.wipe_clip(reg, tmp_path / "w.mov", name="wipe-blinds", aspect="16x9",
                       cut=10.0, size=(1920, 1080))
    assert clip is not None and got["n"] == (8, 12)
    assert clip.start == pytest.approx(10.0 - 3 / 12)
    assert clip.end == pytest.approx(clip.start + 8 / 12)
    assert B.wipe_clip(reg, tmp_path / "x.mov", name="wipe-blinds", aspect="16x9",
                       cut=0.1, size=(1920, 1080)) is None
