"""3D Dennis's lines drawn from the render's passes (room3d/lines.py) and the
EXR those passes come in (room3d/exr.py): plain numbers, no Blender."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "room3d" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lines = _load("dennis_lines", "lines.py")
exr = _load("dennis_exr", "exr.py")

H, W = 40, 60


def _scene():
    """An empty frame, nothing of him or the room in it, with every normal
    and the way back to the camera both +z."""
    depth = np.full((H, W), np.inf, np.float32)
    normal = np.zeros((H, W, 3), np.float32)
    normal[..., 2] = 1.0
    obj = np.zeros((H, W), np.float32)
    mat = np.zeros((H, W), np.float32)
    toward = np.zeros((H, W, 3), np.float32)
    toward[..., 2] = 1.0
    return depth, normal, obj, mat, toward


def _block(scene, y0, y1, x0, x1, *, d, o, m):
    depth, normal, obj, mat, _ = scene
    depth[y0:y1, x0:x1] = d
    obj[y0:y1, x0:x1] = o
    mat[y0:y1, x0:x1] = m


def _edges(scene):
    return lines.edges(*scene[:4], toward=scene[4])


def test_his_outline_against_nothing_is_on_his_side_and_nothing_inside():
    s = _scene()
    _block(s, 10, 30, 20, 40, d=2.0, o=1, m=1)
    outline, detail = _edges(s)
    ring = np.zeros((H, W), bool)
    ring[10:30, 20:40] = True
    ring[11:29, 21:39] = False
    assert (outline == ring).all()
    assert not detail.any()


def test_the_room_in_front_of_him_gets_no_line():
    s = _scene()
    _block(s, 10, 30, 20, 40, d=2.0, o=1, m=1)
    _block(s, 20, 30, 20, 40, d=1.5, o=0, m=0)        # the desk over his lower half
    outline, _ = _edges(s)
    assert not outline[19, 21:39].any()               # where the desk cuts him off
    assert outline[10, 21:39].all()                   # his top edge, against nothing


def test_a_one_pixel_slit_between_two_of_his_parts_is_no_line():
    s = _scene()
    _block(s, 10, 30, 10, 25, d=2.0, o=1, m=1)        # his side
    _block(s, 10, 30, 26, 40, d=2.0, o=2, m=1)        # his arm, a ray slipped between
    outline, _ = _edges(s)
    assert not outline[12:28, 24:27].any()
    assert outline[12:28, 10].all() and outline[12:28, 39].all()


def test_two_parts_of_one_stuff_meeting_flush_are_one_surface():
    s = _scene()
    _block(s, 10, 30, 10, 25, d=2.0, o=1, m=1)        # sleeve
    _block(s, 10, 30, 25, 40, d=2.0, o=2, m=1)        # sweater body
    outline, detail = _edges(s)
    assert not outline[12:28, 23:27].any()
    assert not detail.any()


def test_a_part_of_another_stuff_on_him_is_drawn_round():
    s = _scene()
    _block(s, 5, 35, 10, 50, d=2.0, o=1, m=1)         # face
    _block(s, 15, 20, 20, 40, d=1.99, o=2, m=2)       # glasses
    outline, _ = _edges(s)
    assert outline[15, 21:39].all() and outline[19, 21:39].all()
    assert not outline[14, 21:39].any()               # drawn on the nearer side


def _nose(edge_facing: float):
    """A face facing the camera with a nose 1 cm in front of it (far less
    than a jump), its edge pixels facing the camera `edge_facing`."""
    s = _scene()
    _block(s, 5, 35, 10, 50, d=2.0, o=1, m=1)
    _block(s, 12, 28, 25, 35, d=1.99, o=2, m=1)
    depth, normal, *_ = s
    tilt = np.sqrt(1 - edge_facing ** 2)
    for x, side in ((25, -1.0), (34, 1.0)):
        normal[12:28, x] = (side * tilt, 0.0, edge_facing)
    return s


def test_a_nose_turning_away_over_the_cheek_is_outlined():
    outline, _ = _edges(_nose(0.3))
    assert outline[14:26, 25].all() and outline[14:26, 34].all()
    assert not outline[14:26, 24].any()               # on the nose, not the cheek


def test_the_same_small_step_facing_the_camera_is_no_line():
    outline, _ = _edges(_nose(1.0))
    assert not outline[14:26, 24:26].any()
    # without the camera's direction there is nothing to tell it by either
    s = _nose(0.3)
    outline, _ = lines.edges(*s[:4])
    assert not outline[14:26, 24:26].any()


def _side_over_arm(facings):
    """His side 2 mm in front of his arm, where they nearly touch: far less
    than any step, but the side's edge pixels are turning away (`facings`,
    one per row from row 5) and the arm behind faces the camera."""
    s = _scene()
    _block(s, 5, 35, 10, 30, d=2.002, o=1, m=1)       # arm, behind
    _block(s, 5, 35, 30, 50, d=2.0, o=2, m=1)         # side, in front
    normal = s[1]
    for k, f in enumerate(facings):
        normal[5 + k, 30] = (-np.sqrt(1 - f * f), 0.0, f)
    return s


def test_where_two_surfaces_nearly_touch_the_one_turning_away_is_outlined():
    outline, _ = _edges(_side_over_arm([0.3] * 30))
    assert outline[8:32, 30].all() and not outline[8:32, 29].any()
    outline, _ = _edges(_side_over_arm([1.0] * 30))   # both square on: one surface
    assert not outline[8:32, 28:32].any()


def test_a_line_carries_over_a_short_stretch_of_weaker_evidence():
    """Sure for ten rows, half sure for five, sure again: one line, not
    two dashes. Half sure all the way, it runs only a few pixels in from the
    outline it starts at, and never down the middle."""
    outline, _ = _edges(_side_over_arm([0.3] * 10 + [0.6] * 5 + [0.3] * 15))
    assert outline[8:32, 30].all()
    outline, _ = _edges(_side_over_arm([0.6] * 30))
    assert not outline[5 + lines.SIL_BRIDGE_PX + 1:35 - lines.SIL_BRIDGE_PX - 1, 28:32].any()


def test_a_speck_is_not_drawn():
    s = _scene()
    _block(s, 5, 35, 10, 50, d=2.0, o=1, m=1)
    _block(s, 20, 21, 30, 31, d=1.99, o=2, m=2)        # one pixel of something else
    outline, detail = _edges(s)
    assert not outline[15:26, 25:36].any() and not detail.any()


def test_a_surface_turning_away_by_itself_is_no_line():
    s = _scene()
    _block(s, 5, 35, 5, 55, d=2.0, o=1, m=1)
    depth, normal, *_ = s
    # a cylinder seen side on: deeper and more askew every pixel to its edge
    for k, x in enumerate(range(40, 55)):
        a = np.radians(5 * (k + 1))
        depth[5:35, x] = 2.0 + 0.001 * (1 - np.cos(a)) / 0.004
        normal[5:35, x] = (np.sin(a), 0.0, np.cos(a))
    outline, detail = _edges(s)
    assert not outline[8:32, 30:54].any()
    assert not detail[8:32, 30:54].any()


def test_a_sharp_turn_of_his_surface_is_a_detail_line():
    s = _scene()
    _block(s, 5, 35, 10, 50, d=2.0, o=1, m=1)
    normal = s[1]
    normal[5:35, 30:50] = (np.sin(np.radians(70)), 0.0, np.cos(np.radians(70)))
    outline, detail = _edges(s)
    assert detail[8:32, 29].all()
    assert not outline[8:32, 28:32].any()


def test_a_normal_blended_with_the_room_beside_him_is_no_turn():
    s = _scene()
    _block(s, 5, 35, 10, 50, d=2.0, o=1, m=1)
    _block(s, 25, 35, 20, 40, d=1.5, o=0, m=0)        # a cup in front
    normal = s[1]
    normal[24, 20:40] = (0.0, 0.9, 0.44)              # his pixels on its rim, smeared
    _, detail = _edges(s)
    assert not detail[22:26, 20:40].any()


def test_toward_points_back_through_each_pixel():
    t = lines.toward((-1, 1, -1), (1, 1, -1), (-1, -1, -1), (4, 2))
    assert t.shape == (2, 4, 3)
    assert np.allclose(np.linalg.norm(t, axis=-1), 1.0)
    # left half points back to the right, the top row back down, all toward +z
    assert (t[:, :2, 0] > 0).all() and (t[:, 2:, 0] < 0).all()
    assert (t[0, :, 1] < 0).all() and (t[1, :, 1] > 0).all()
    assert (t[..., 2] > 0).all()
    assert np.allclose(t[0, 0], -t[1, 3] * (1, 1, -1))


def test_coverage_is_full_on_the_line_and_fades_over_its_last_pixel():
    m = np.zeros((9, 9), bool)
    m[4, 4] = True
    a = lines.coverage(m, 3.0)
    assert a[4, 4] == 1.0 and a[4, 5] == 1.0 and a[4, 6] == 0.0
    assert 0.0 < a[3, 5] < 1.0
    assert not lines.coverage(np.zeros((3, 3), bool), 3.0).any()


def test_ink_lays_the_colour_over_him_and_over_nothing():
    rgba = np.zeros((1, 2, 4), np.uint8)
    rgba[0, 0] = (200, 100, 50, 255)
    a = np.array([[0.5, 1.0]], np.float32)
    out = lines.ink(rgba, a, (0, 0, 0))
    assert tuple(out[0, 0]) == (100, 50, 25, 255)
    assert tuple(out[0, 1]) == (0, 0, 0, 255)


# --------------------------------------------------------------------- exr

def _attr(name: str, kind: str, value: bytes) -> bytes:
    return name.encode() + b"\0" + kind.encode() + b"\0" + struct.pack("<i", len(value)) + value


def _header(chans, w, h, part: str | None = None, chunks: int | None = None) -> bytes:
    chlist = b"".join(c.encode() + b"\0" + struct.pack("<i", t) + b"\0\0\0\0" +
                      struct.pack("<ii", 1, 1) for c, t, _ in chans) + b"\0"
    box = struct.pack("<4i", 0, 0, w - 1, h - 1)
    out = (_attr("channels", "chlist", chlist) + _attr("compression", "compression", b"\0")
           + _attr("dataWindow", "box2i", box) + _attr("displayWindow", "box2i", box)
           + _attr("lineOrder", "lineOrder", b"\0"))
    if part is not None:
        out += (_attr("name", "string", part.encode()) + _attr("type", "string", b"scanlineimage")
                + _attr("chunkCount", "int", struct.pack("<i", chunks)))
    return out + b"\0"


def _lines(chans, w, h, part_no: int | None):
    """Each scanline chunk, in order."""
    dtype = {0: "<u4", 1: "<f2", 2: "<f4"}
    for y in range(h):
        data = b"".join(np.asarray(px[y], dtype[t]).tobytes() for _, t, px in chans)
        lead = b"" if part_no is None else struct.pack("<i", part_no)
        yield lead + struct.pack("<ii", y, len(data)) + data


def _write(path: Path, parts: list[tuple[str | None, list]], w: int, h: int) -> None:
    multi = parts[0][0] is not None
    head = b"\x76\x2f\x31\x01" + struct.pack("<i", 2 | (0x1000 if multi else 0))
    head += b"".join(_header(ch, w, h, name, h) for name, ch in parts)
    if multi:
        head += b"\0"
    chunks = [list(_lines(ch, w, h, k if multi else None)) for k, (_, ch) in enumerate(parts)]
    pos = len(head) + 8 * h * len(parts)
    table, body = b"", b""
    for part in chunks:
        for c in part:
            table += struct.pack("<Q", pos + len(body))
            body += c
    path.write_bytes(head + table + body)


def test_reads_a_single_part_exr_of_every_pixel_type(tmp_path):
    w, h = 5, 3
    z = np.arange(15, dtype=np.float32).reshape(h, w) / 4
    n = np.linspace(-1, 1, 15, dtype=np.float32).reshape(h, w)
    i = np.arange(15, dtype=np.uint32).reshape(h, w)
    f = tmp_path / "one.exr"
    _write(f, [(None, [("A", 1, n), ("B", 0, i), ("Z", 2, z)])], w, h)
    got = exr.read_exr(f)
    assert set(got) == {"A", "B", "Z"}
    assert np.allclose(got["Z"], z) and got["Z"].dtype == np.float32
    assert np.allclose(got["A"], n, atol=1e-3)
    assert (got["B"] == i).all()


def test_reads_every_part_of_a_multipart_exr(tmp_path):
    w, h = 4, 2
    d = np.full((h, w), 2.5, np.float32)
    o = np.array([[0, 1, 1, 0], [2, 2, 0, 0]], np.float32)
    f = tmp_path / "many.exr"
    _write(f, [("ViewLayer.Depth", [("V", 2, d)]), ("ViewLayer.Object Index", [("V", 2, o)])],
           w, h)
    got = exr.read_exr(f)
    assert np.allclose(got["ViewLayer.Depth.V"], d)
    assert (got["ViewLayer.Object Index.V"] == o).all()


def test_refuses_what_it_cannot_read(tmp_path):
    import pytest

    bad = tmp_path / "x.exr"
    bad.write_bytes(b"\x89PNG....")
    with pytest.raises(ValueError):
        exr.read_exr(bad)
    w, h = 2, 1
    f = tmp_path / "zip.exr"
    _write(f, [(None, [("Z", 2, np.zeros((h, w), np.float32))])], w, h)
    b = bytearray(f.read_bytes())
    at = b.index(b"compression\0compression\0") + len(b"compression\0compression\0") + 4
    b[at] = 3                                          # ZIP
    f.write_bytes(bytes(b))
    with pytest.raises(ValueError, match="compressed"):
        exr.read_exr(f)
