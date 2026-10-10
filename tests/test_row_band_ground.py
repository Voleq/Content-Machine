"""A row band is drawn for the plate's ground, not for the episode's hour.

Rebuild-41 drew data plates per ground (a paper sheet is cream at both hours)
while `overlays/row-band` stayed per hour. At night the hour's band is navy,
and on a paper sheet that is a slab under black figures: the highlighted row
was the one row nobody could read.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.plate_frames import render_frame, row_band

SHEET = "tables/numbers-sheet-4r-16x9"


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir)


def _rgb(hex_):
    h = hex_.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)])


def _banded(reg):
    return [(p, n, s) for p in reg.assets.values() if p.ground
            for n, s in p.slots.items() if s.overlay == "overlays/row-band"]


@pytest.mark.parametrize("hour", ["night", "dusk"])
def test_every_band_is_the_one_drawn_nearest_its_plate_s_ground(reg, hour):
    view = reg.at(hour)
    banded = _banded(view)
    assert len(banded) > 20, "the kit's sheets lost their row bands"
    drawn = {h: _rgb(view.inks(view.plate_at("overlays/row-band", h))["band"])
             for h in view.hour_suffixes}
    for plate, name, slot in banded:
        want = _rgb(view.inks(plate)["band"])
        got = row_band(view, plate, slot)
        best = min(drawn, key=lambda h: ((drawn[h] - want) ** 2).sum())
        assert got.hour == best, (plate.key, name, plate.ground, got.key)


def test_a_paper_sheet_at_night_lights_its_row_cream_not_navy(reg, settings):
    view = reg.at("night")
    sheet = view.get(SHEET)
    assert sheet.ground == "paper"
    values = {"label-1": "Revenue", "band-1": "1"}
    bare = np.asarray(render_frame(sheet, 0, {"label-1": "Revenue"}, settings, view)
                      .convert("RGB")).astype(int)
    lit = np.asarray(render_frame(sheet, 0, values, settings, view)
                     .convert("RGB")).astype(int)
    changed = np.abs(lit - bare).max(axis=2) > 0
    assert changed.any(), "band-1 drew nothing"
    band = np.median(lit[changed], axis=0)
    paper = _rgb(view.inks(sheet)["band"])
    assert np.abs(band - paper).max() < 40, (band, paper)
