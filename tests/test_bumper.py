"""Design's chapter bumper and the wipes the LONG lays over its cuts."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import bumper as B
from pipeline import motion as M
from pipeline.moves import OUT_FPS


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
    assert len(frames) == round((plate.hold_s or 2.0) * OUT_FPS) == 60


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


def _turn(reg):
    """(last video frame before the turn, first one landed) of the bumper's
    tick-over, from design's frames at its 12 a second."""
    first, n = B.tick_timing(reg, reg.get(reg.aspect_key("structure/chapter-bumper", "16x9")))
    assert (first, n) == (3, 6), "design's tick-over: the fourth frame of the hold, six frames"
    return (int(first * OUT_FPS / M.FPS),
            int(np.ceil((first + n - 1) * OUT_FPS / M.FPS)))


def test_the_number_turns_over_and_nothing_else_changes(frames, reg):
    box = _num_box(reg)
    before, landed = _turn(reg)
    a = [np.asarray(f.convert("RGB"), dtype=np.int16) for f in frames]
    # Before the tick the old number holds; once it lands the new one does.
    assert np.abs(a[0] - a[before]).max() < 60      # boil only
    inside = lambda i, j: np.abs(a[i] - a[j])[box[1]:box[3], box[0]:box[2]].mean()
    assert inside(before, landed) > 5
    assert inside(landed, len(a) - 1) < 3
    # Outside the number, the frames differ only by the plate's own boil.
    outside = np.abs(a[before] - a[(before + landed) // 2]).copy()
    outside[box[1]:box[3], box[0]:box[2]] = 0
    assert outside.mean() < 3


def test_the_number_moves_on_every_video_frame_of_the_turn(frames, reg):
    """2 Oct 2026: at design's 12 a second the turn stepped two and a half
    video frames at a time. Played at the video's rate, every frame of it is
    a new position."""
    box = _num_box(reg)
    before, landed = _turn(reg)
    # From the first frame after the start: on that one design's ease has
    # barely left rest, which is the ease, not a step.
    a = [np.asarray(f.convert("L"), dtype=np.int16)[box[1]:box[3], box[0]:box[2]]
         for f in frames[before + 1:landed + 1]]
    assert len(a) >= 12
    still = [i for i in range(1, len(a)) if np.abs(a[i] - a[i - 1]).mean() < 0.5]
    assert not still, f"the number sits still on frames {still} of its turn"


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


@pytest.mark.parametrize("hour", ["night", "dusk"])
def test_the_long_s_wipes_onto_paper_are_paper_at_every_hour(reg, hour):
    """10 Oct 2026: the long's blinds into each chapter bumper, the page off the
    opening title and the sweep off the close were navy at night, a dark
    flash between paper cards. Given the bumper's ground, every one is paper."""
    at = reg.at(hour)
    paper = at.get(at.aspect_key("structure/chapter-bumper", "16x9"))
    assert paper.ground == "paper"
    for name in ("wipe-blinds", "wipe-sweep", "wipe-page"):
        frames, cut = B.wipe_frames(at, name, "16x9", (192, 108), ground=paper)
        cover = np.asarray(frames[cut]).astype(float)
        drawn = cover[..., 3] > 200
        assert drawn.mean() > 0.9, (hour, name)
        assert cover[drawn][:, :3].mean() > 180, (hour, name)
