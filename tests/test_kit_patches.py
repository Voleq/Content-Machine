"""The bot's own patches to the vendored kit, pinned.

`kit/` is design's delivery and gets replaced wholesale on every drop. One fix
lives in it on this side (46544f6): rebuild-41's `engine/grounds.js` grew a
9:16 type box past its zone, which slid right-aligned y-axis labels into the
plot on eleven charts, and the bot's patch stops a grown box 14 units short of
any data region. A swap that drops it reverts that silently — the manifests
regenerate without complaint and the labels sit on the bars again. This fails
instead, on the commit that would lose it.
"""

from __future__ import annotations

from pathlib import Path

GROUNDS = Path(__file__).resolve().parents[1] / "kit" / "engine" / "grounds.js"


def test_the_r41_axis_label_patch_survives_the_kit_swap():
    src = GROUNDS.read_text(encoding="utf-8")
    assert "DATA_GAP" in src and "R41" in src, (
        "kit/engine/grounds.js no longer carries the bot's R41 patch (a grown "
        "9:16 type box stops DATA_GAP short of a data region). Re-apply it "
        "from 46544f6, or confirm design's drop includes the fix, then "
        "regenerate the manifests with `node engine/emit.js`.")
    # The patch is only worth anything if the regions it protects are named.
    for region in ("plot-area", "bars", "path"):
        assert f"'{region}'" in src
