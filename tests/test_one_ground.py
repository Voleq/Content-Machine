"""Every plate on one ground: paper.

Valentin, 10 Oct 2026, on design's mix of cream paper plates and navy chart
plates: "i do not get this alternation between white background and dark
background plates", then "we don't change any plates any more in design,
let's stick to only one", then "the paper looks better". The ground is one
table in design's tokens, so the ingest puts every family on paper in its
staged copy and draws from that; design's own emitter, export and audit run
again on it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ingest():
    spec = importlib.util.spec_from_file_location("ingest_kit", ROOT / "scripts" / "ingest_kit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_ingest_puts_every_family_on_paper(tmp_path, monkeypatch):
    ingest = _ingest()
    assert ingest.PLATE_GROUND == "paper"
    tokens = json.loads((ROOT / "kit" / "design-tokens.json").read_text(encoding="utf-8"))
    shipped = tokens["plateStyle"]["grounds"]
    (tmp_path / "design-tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
    ran = []
    monkeypatch.setattr(ingest, "_node", lambda cmd, cwd: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(ingest, "_audit", lambda staged, when: [])
    assert ingest._one_ground(tmp_path) == []
    got = json.loads((tmp_path / "design-tokens.json").read_text(encoding="utf-8"))
    grounds = got["plateStyle"]["grounds"]
    assert grounds["screen"] == [] and grounds["screenKeys"] == []
    assert set(grounds["paper"]) == set(shipped["paper"]) | set(shipped["screen"])
    assert grounds["mark"] == shipped["mark"]
    # design's emitter and export redraw the kit from the new table
    assert [c[1] for c in ran] == ["engine/emit.js", "engine/export.js"]


def test_nothing_is_changed_when_the_mix_is_asked_for(tmp_path):
    assert _ingest()._one_ground(tmp_path, None) == []


def test_every_installed_plate_is_on_paper():
    from config import Settings
    from pipeline.plates import load_plates

    reg = load_plates(Settings(MOCK_MODE=True, _env_file=None).assets_dir)
    grounds = {p.ground for p in reg.assets.values() if p.ground}
    if "screen" in grounds:
        pytest.fail("a navy plate is installed: rerun `python scripts/ingest_kit.py kit`")
    assert "paper" in grounds
    assert reg.get("charts/bars-6y-9x16").ground == "paper"


def test_a_quote_mark_cut_by_the_frame_edge_is_papered_over():
    """Design's restyle moved the quote card's type to the margin and pushed
    its opening marks past the left edge: what was left was a red tick at the
    edge of the frame (10 Oct 2026). Papered over, in both aspects."""
    import numpy as np

    from config import Settings
    from pipeline.plate_frames import clipped_marks, render_frame
    from pipeline.plates import load_plates

    settings = Settings(MOCK_MODE=True, _env_file=None)
    reg = load_plates(settings.assets_dir)
    for aspect in ("9x16", "16x9"):
        plate = reg.get(reg.aspect_key("cards/quote-pull", aspect))
        marks = clipped_marks(plate)
        if not marks:
            pytest.skip("this kit draws its quote marks on the canvas")
        img = np.asarray(render_frame(plate, 0, {}, settings, reg).convert("RGB")).astype(int)
        k = img.shape[1] / plate.canvas[0]
        for x, y, w, h in marks:
            patch = img[int(y * k):int((y + h) * k), int(x * k):int((x + w) * k)]
            # no red left: the attention ink is far redder than it is green
            assert not ((patch[..., 0] - patch[..., 1]) > 60).any(), (aspect, (x, y, w, h))
